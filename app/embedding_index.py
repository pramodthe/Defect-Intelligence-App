import json
from app.embeddings import configured, embedding_spec, public_settings, selected_config
from app.projections import stage
from app.store import Store, canonical, new_id
from app import visual_embeddings as visual
from app.ontology import Ontology


def rebuild_profile(store: Store):
    text = embedding_spec(selected_config(store)).profile
    config = visual.selected_config(store)
    return text if not config.visual_embedding_enabled or config.visual_embedding_provider == 'disabled' else [text, visual.spec(config).profile]


def save_settings(store: Store, payload: dict) -> dict:
    config = store.config.model_copy(update={k: v for k, v in payload.items() if k != "expected_version"})
    embedding_spec(config)
    with store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT value FROM workspace WHERE key='maintenance' AND value='1'").fetchone():
            raise ValueError("Wait for workspace recovery before changing embedding settings")
        current = con.execute("SELECT value FROM workspace WHERE key='embedding_settings'").fetchone()
        version = json.loads(current[0])["version"] if current else 1
        if version != payload["expected_version"]:
            raise ValueError("Stale embedding settings; reload before saving")
        if con.execute("SELECT id FROM outbox WHERE kind='embedding_reindex' AND state IN ('pending','running')").fetchone():
            raise ValueError("Wait for the current index rebuild before changing providers")
        value = {"version": version + 1, **{k: payload[k] for k in
            ("embedding_provider", "embedding_model", "embedding_dimensions")}}
        con.execute("INSERT INTO workspace(key,value) VALUES('embedding_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (canonical(value),))
    return {"status": "Embedding settings saved. Rebuild the search index to apply them to existing reports.",
            **public_settings(store)}


def queue_reindex(store: Store) -> dict:
    domain_version = Ontology(store).domain_version
    visual_config = visual.selected_config(store)
    if visual_config.visual_embedding_enabled and visual_config.visual_embedding_provider != 'disabled' and not visual.configured(store):
        raise ValueError('Configure the visual key/deployment and pass the synthetic image test before rebuilding')
    if not (configured(store) or visual.configured(store)) or not store.config.qdrant_url:
        raise ValueError("Configure Qdrant and the selected embedding provider's server-side credential first")
    with store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT value FROM workspace WHERE key='maintenance' AND value='1'").fetchone():
            raise ValueError("Wait for workspace recovery before rebuilding")
        if con.execute("SELECT id FROM outbox WHERE kind='embedding_reindex' AND state IN ('pending','running')").fetchone():
            raise ValueError("An embedding rebuild is already queued or running")
        manifest = con.execute("SELECT value FROM workspace WHERE key='manifest'").fetchone()[0]
        docs = [r[0] for r in con.execute("SELECT document_id FROM manifest_members WHERE manifest_id=? ORDER BY document_id", (manifest,))]
        if not docs:
            raise ValueError("Import and publish a report before rebuilding")
        jid = new_id("job_embedding_reindex")
        payload = {"manifest_id": manifest, "profile": rebuild_profile(store),
                   'domain_version': domain_version,
                   "documents": docs, "projections": {}, "completed_documents": 0}
        con.execute("INSERT INTO outbox VALUES(?,?,?,?)", (jid, "embedding_reindex", canonical(payload), "pending"))
    return {"id": jid, "status": "Search index rebuild queued. The current source library remains available."}


def rebuild(store: Store, ontology, event: dict) -> dict:
    payload = json.loads(event["payload"])
    if payload.get('domain_version',ontology.domain_version) != ontology.domain_version:
        raise ValueError('Domain schema changed; queue a new rebuild')
    if payload["profile"] != rebuild_profile(store):
        raise ValueError("Embedding configuration changed; queue a new rebuild")
    if store.active_manifest() != payload["manifest_id"]:
        raise ValueError("Source library changed; queue a new rebuild")
    for doc in payload["documents"]:
        if doc in payload["projections"]:
            continue
        result = stage(store, doc, ontology, embedding_owner=event["id"])
        if configured(store) and result["receipts"]["vectors"]["state"] != "ready":
            raise ValueError("Embedding projection did not validate")
        if visual.configured(store) and result['receipts'].get('visuals', {}).get('state') != 'ready':
            raise ValueError('Visual projection did not validate')
        payload["projections"][doc] = result["projection_id"]
        payload["completed_documents"] += 1
        store.execute("UPDATE outbox SET payload=json_set(?,'$.lease_until',COALESCE(json_extract(payload,'$.lease_until'),0)) WHERE id=?",
                      (canonical(payload), event["id"]))
    manifest = store.activate_reindex(payload["projections"], payload["manifest_id"],
                                     {"embedding_profile": payload["profile"], "rebuild": event["id"]},
                                     event_id=event["id"], event_payload=payload)
    return {"manifest_id": manifest}
