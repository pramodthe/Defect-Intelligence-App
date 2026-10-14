import asyncio
import json
import sys
import time
import uuid
from typing import Any
from langgraph.types import Command
from app.ontology import Ontology
from app.settings import settings
from app.store import Store
from app.workflows import build_ingestion, checkpoint_session, INGEST_VERSION
from app.corrections import republish_correction
from app.embedding_index import rebuild
from app.store import canonical


def claim(store: Store, owner: str):
    with store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        job = con.execute("SELECT * FROM jobs WHERE cancel=0 AND attempts<3 AND (status='queued' OR (lease_until IS NOT NULL AND lease_until<?)) ORDER BY created LIMIT 1", (time.time(),)).fetchone()
        if not job:
            return None
        con.execute("UPDATE jobs SET status='running',lease_owner=?,lease_until=?,attempts=attempts+1 WHERE id=?", (owner, time.time() + 90, job["id"]))
        return dict(job)


async def heartbeat(store: Store, job_id: str, owner: str):
    while True:
        await asyncio.sleep(15)
        store.execute("UPDATE jobs SET lease_until=? WHERE id=? AND lease_owner=?", (time.time() + 90, job_id, owner))


async def process(store: Store, graph, job: dict, owner: str):
    if job["graph_version"] != INGEST_VERSION:
        raise ValueError("Graph version mismatch; new migration/job required")
    hb = asyncio.create_task(heartbeat(store, job["id"], owner))
    config = {"configurable": {"thread_id": "ingest:" + job["id"]}, "recursion_limit": 64}
    try:
        snapshot = await graph.aget_state(config)
        arg: Any = None if snapshot.values else {"job_id": job["id"], "document_id": job["document_id"], "graph_version": INGEST_VERSION}
        if snapshot.interrupts:
            if store.config.text_provider == "disabled":
                store.execute("UPDATE jobs SET status='awaiting_configuration',lease_owner=NULL,lease_until=NULL WHERE id=?", (job["id"],))
                return
            arg = Command(resume={"configuration": "explicitly_enabled"})
        await asyncio.wait_for(graph.ainvoke(arg, config), store.config.ingest_seconds)
    except Exception as exc:
        cancelled = store.require("SELECT cancel FROM jobs WHERE id=?", (job["id"],))["cancel"]
        status = "cancelled" if cancelled else "failed"
        reason = str(exc)[:250]
        store.execute("UPDATE jobs SET status=?,error=?,lease_owner=NULL,lease_until=NULL WHERE id=?", (status, reason, job["id"]))
        store.execute("UPDATE documents SET status=? WHERE id=?", (status, job["document_id"]))
        store.event(job["id"], "failed", {"status": status, "reason": reason})
        print(json.dumps({"job": job["id"], "status": status, "reason": reason}), flush=True)
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass


async def reindex_heartbeat(store: Store, event_id: str):
    while True:
        await asyncio.sleep(15)
        store.execute("UPDATE outbox SET payload=json_set(payload,'$.lease_until',?) WHERE id=? AND state='running'",
                      (time.time() + 90, event_id))
        store.execute("INSERT INTO workspace(key,value) VALUES('worker_heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(time.time()),))


async def process_reindex(store: Store, ontology, event_id: str):
    pulse = asyncio.create_task(reindex_heartbeat(store, event_id))
    try:
        current = store.require("SELECT * FROM outbox WHERE id=?", (event_id,))
        return await asyncio.to_thread(rebuild, store, ontology, current)
    finally:
        pulse.cancel()
        try:
            await pulse
        except asyncio.CancelledError:
            pass


async def main(once=False):
    store = Store(settings)
    store.initialize()
    from app.providers import apply_saved_text_settings
    apply_saved_text_settings(store)
    ontology = Ontology(store)
    owner = uuid.uuid4().hex
    async with checkpoint_session(store) as saver:
        graph = build_ingestion(store, saver, ontology)
        print("Worker ready; private source text is excluded from logs", flush=True)
        while True:
            store.execute("INSERT INTO workspace(key,value) VALUES('worker_heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(time.time()),))
            maintenance=store.one("SELECT value FROM workspace WHERE key='maintenance'")
            if maintenance and maintenance['value']=='1':
                await asyncio.sleep(1)
                continue
            # Expired rebuild leases can resume completed local batches. Unknown provider attempts cannot replay.
            store.execute("UPDATE outbox SET state='pending' WHERE kind='embedding_reindex' AND state='running' AND COALESCE(json_extract(payload,'$.lease_until'),0)<?", (time.time(),))
            correction = store.one("SELECT * FROM outbox WHERE state='pending' ORDER BY rowid LIMIT 1")
            if correction:
                try:
                    if correction['kind'] == 'embedding_reindex':
                        with store.connect() as con:
                            updated = con.execute("UPDATE outbox SET state='running',payload=json_set(payload,'$.lease_until',?) WHERE id=? AND state='pending'", (time.time() + 90, correction['id'])).rowcount
                        if updated:
                            await process_reindex(store, ontology, correction['id'])
                    else:
                        await asyncio.to_thread(republish_correction, store, ontology, correction)
                except Exception as exc:
                    current = store.require("SELECT payload FROM outbox WHERE id=?", (correction['id'],))
                    payload = json.loads(current['payload'])
                    payload['error'] = type(exc).__name__ + ': rebuild failed; current library was retained. Check credentials and queue an explicit retry.'
                    store.execute("UPDATE outbox SET state='failed',payload=? WHERE id=?", (canonical(payload), correction["id"]))
                    print(json.dumps({"outbox": correction["id"], "status": "failed", "reason": type(exc).__name__}), flush=True)
            job = claim(store, owner)
            if job:
                await process(store, graph, job, owner)
            elif once:
                return
            else:
                await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main("--once" in sys.argv))
