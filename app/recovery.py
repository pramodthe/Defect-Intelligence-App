import json
import os
import sqlite3
import tempfile
import time
import subprocess
import shutil
from contextlib import contextmanager
from urllib.parse import urlparse,unquote
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from app.store import Store, canonical, digest, identity


@contextmanager
def maintenance(store:Store):
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        existing=con.execute("SELECT value FROM workspace WHERE key='maintenance'").fetchone()
        if existing and existing[0]=='1':
            raise ValueError('Workspace already in a recovery operation')
        con.execute("INSERT INTO workspace(key,value) VALUES('maintenance','1') ON CONFLICT(key) DO UPDATE SET value='1'")
    try:
        yield
    finally:
        store.execute("UPDATE workspace SET value='0' WHERE key='maintenance'")


def pg_command(store:Store,program:str,path:Path):
    parsed=urlparse(store.config.langgraph_checkpoint_dsn)
    if parsed.hostname not in {'127.0.0.1','localhost','postgres'} or not (parsed.path=='/checkpoints' or parsed.path.startswith('/checkpoint_test_')):
        raise ValueError('Automatic workflow recovery is restricted to the dedicated local checkpoint database')
    native=Path(__file__).resolve().parents[1]/'.tools/postgresql-17.6/pgsql/bin'/(program+'.exe')
    binary=str(native) if native.is_file() else shutil.which(program)
    if not binary:
        raise ValueError('PostgreSQL recovery client unavailable')
    args=[binary,'-h',parsed.hostname,'-p',str(parsed.port or 5432),'-U',unquote(parsed.username or ''),'-d',parsed.path.lstrip('/')]
    args += ['--format=custom','--no-owner','--no-acl','-f',str(path)] if program=='pg_dump' else ['--clean','--if-exists','--no-owner','--no-acl','--single-transaction',str(path)]
    env={**os.environ,'PGPASSWORD':unquote(parsed.password or '')}
    result=subprocess.run(args,env=env,capture_output=True,timeout=60)
    if result.returncode:
        raise ValueError('PostgreSQL '+program+' failed; prior recovery snapshot retained')


def _backup(store: Store) -> dict:
    active = store.require("SELECT COUNT(*) n FROM jobs WHERE lease_until>?", (time.time(),))["n"]
    runs = store.require("SELECT COUNT(*) n FROM runs WHERE status='running'")["n"]
    rebuilds = store.require("SELECT COUNT(*) n FROM outbox WHERE kind='embedding_reindex' AND state='running'")["n"]
    if active or runs or rebuilds:
        raise ValueError("Wait for active workers/research to quiesce before backup")
    target_dir = store.root / "backups"
    target_dir.mkdir(exist_ok=True)
    bid = identity("backup", time.time_ns())
    db_copy = target_dir / (bid + ".sqlite")
    with store.connect() as source:
        dest = sqlite3.connect(db_copy)
        source.backup(dest)
        dest.close()
    assets = store.all("SELECT * FROM assets")
    files = {"catalog.sqlite": db_copy}
    workflow_file=target_dir/(bid+'.pgdump')
    workflow='not configured'
    if store.config.checkpoint_backend=='postgres':
        pg_command(store,'pg_dump',workflow_file)
        files['workflow.pgdump']=workflow_file
        workflow='included'
    for a in assets:
        files["workspace/" + a["path"]] = store.asset_path(a["id"])
    knowledge = Path(__file__).resolve().parents[1] / "knowledge"
    for path in knowledge.rglob("*.json"):
        files["knowledge/" + path.relative_to(knowledge).as_posix()] = path
    checksums = {name: digest(path.read_bytes()) for name, path in files.items()}
    manifest = {"schema": "backup/1", "id": bid, "created": time.time(), "files": checksums,
        "active_manifest": store.active_manifest(), "checkpoint_backend": store.config.checkpoint_backend,
        "workflow_state": workflow,
        "graph_versions": ["ingestion/1", "research/1"], "projections": "verify/rebuild from canonical receipts"}
    target = target_dir / (bid + ".zip")
    with ZipFile(target, "w", ZIP_DEFLATED) as z:
        for name, path in files.items():
            z.write(path, name)
        z.writestr("manifest.json", canonical(manifest))
    db_copy.unlink()
    if workflow_file.exists():
        workflow_file.unlink()
    store.insert("workspace", {"key": bid, "value": canonical({"path": target.name, "manifest": manifest})})
    return {"id": bid, "size": target.stat().st_size, "manifest": manifest}


def backup(store:Store)->dict:
    with maintenance(store):
        return _backup(store)


def _restore(store: Store, backup_id: str) -> dict:
    if store.require("SELECT COUNT(*) n FROM jobs WHERE lease_until>?", (time.time(),))["n"] or store.require("SELECT COUNT(*) n FROM runs WHERE status='running'")["n"]:
        raise ValueError("Quiesce active processing before restore")
    record = store.one("SELECT value FROM workspace WHERE key=?", (backup_id,))
    if not record or not backup_id.startswith("backup_"):
        raise KeyError("Unknown managed backup")
    name = json.loads(record["value"])["path"]
    archive = (store.root / "backups" / name).resolve()
    if not archive.is_relative_to(store.root / "backups"):
        raise ValueError("Invalid backup target")
    with tempfile.TemporaryDirectory(dir=store.root) as tmp:
        tmp_path = Path(tmp)
        with ZipFile(archive) as z:
            if len(z.infolist()) > 100000 or sum(i.file_size for i in z.infolist()) > 20 * 1024**3:
                raise ValueError("Backup expansion limit exceeded")
            manifest = json.loads(z.read("manifest.json"))
            if manifest.get("schema") != "backup/1":
                raise ValueError("Unsupported backup schema")
            if digest(manifest)!=digest(json.loads(record['value'])['manifest']):
                raise ValueError('Backup manifest differs from its managed canonical receipt')
            for path, checksum in manifest["files"].items():
                dest = (tmp_path / path).resolve()
                if not dest.is_relative_to(tmp_path):
                    raise ValueError("Unsafe backup member")
                raw = z.read(path)
                if digest(raw) != checksum:
                    raise ValueError("Backup checksum mismatch")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
        restored_db = tmp_path / "catalog.sqlite"
        with sqlite3.connect(restored_db) as con:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or con.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Backup canonical integrity failure")
            if con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] != 1:
                raise ValueError("Incompatible schema")
            assets = list(con.execute("SELECT path,sha256 FROM assets"))
            for path, sha in assets:
                file = tmp_path / "workspace" / path
                if not file.is_file() or digest(file.read_bytes()) != sha:
                    raise ValueError("Restored asset identity mismatch")
            # Never resume a checkpoint whose cross-store artifact lineage was not restored.
            con.execute("UPDATE runs SET status='interrupted',stale=1,error='Restored canonical snapshot; start a new run' WHERE status IN ('running','clarification_required','queued','interrupted')")
            con.execute("UPDATE jobs SET lease_owner=NULL,lease_until=NULL,status='restored_requires_rebuild' WHERE status NOT IN ('ready','partial','awaiting_configuration')")
            con.commit()
        con.close()
        # Rebuild/verify staged projections against the validated temporary catalog before activation.
        # A store failure here leaves the prior canonical/checkpoint workspace untouched.
        from app.ontology import Ontology
        from app.projections import stage
        preview=Store(store.config.model_copy(update={'workspace_root':tmp_path}))
        preview.initialize()
        catalog=Ontology(preview)
        members=preview.all('SELECT document_id FROM manifest_members WHERE manifest_id=?',(manifest['active_manifest'],))
        for member in members:
            projection=stage(preview,member['document_id'],catalog)
            preview.activate(projection['projection_id'],{'profile':projection['profile'],'receipts':projection['receipts'],'recovery':'verified staged rebuild'})
        with preview.connect() as checkpoint_connection:
            checkpoint_connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        recovery = _backup(store)
        retained_backups=store.all("SELECT * FROM workspace WHERE key LIKE 'backup_%'")
        if manifest.get('workflow_state')=='included':
            try:
                pg_command(store,'pg_restore',tmp_path/'workflow.pgdump')
            except Exception:
                # Restore the pre-operation workflow snapshot before reporting a failed operation.
                recovery_record=store.require('SELECT value FROM workspace WHERE key=?',(recovery['id'],))
                recovery_path=store.root/'backups'/json.loads(recovery_record['value'])['path']
                with ZipFile(recovery_path) as z:
                    fallback=tmp_path/'recovery.pgdump'
                    fallback.write_bytes(z.read('workflow.pgdump'))
                pg_command(store,'pg_restore',fallback)
                raise
            from langgraph.checkpoint.postgres import PostgresSaver
            with PostgresSaver.from_conn_string(store.config.langgraph_checkpoint_dsn) as saver:
                check=sqlite3.connect(restored_db)
                try:
                    for run_id,checkpoint_id,graph_version,manifest_id,context_id in check.execute('SELECT id,checkpoint_id,graph_version,manifest_id,final_context_id FROM runs WHERE checkpoint_id IS NOT NULL').fetchall():
                        checkpoint=saver.get_tuple({'configurable':{'thread_id':'research:'+run_id,'checkpoint_id':checkpoint_id}})
                        state=checkpoint.checkpoint.get('channel_values',{}) if checkpoint else {}
                        valid=state.get('graph_version')==graph_version and state.get('manifest_id')==manifest_id and state.get('context_id')==context_id
                        valid=valid and all(check.execute('SELECT id FROM chunk_revisions WHERE id=?',(cid,)).fetchone() for cid in state.get('evidence_ids',[]))
                        if not valid:
                            check.execute("UPDATE runs SET status='interrupted',stale=1,error='Checkpoint/canonical references incompatible; new run required' WHERE id=?",(run_id,))
                    check.commit()
                finally:
                    check.close()
        # Assets are additive and immutable. Activation happens only after all checks above.
        for path, _ in assets:
            target = store.root / path
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_path / "workspace" / path, target)
        with store.connect() as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for suffix in ["-wal", "-shm"]:
            sidecar = Path(str(store.db) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.replace(restored_db, store.db)
        for entry in retained_backups:
            store.insert('workspace',entry)
    return {"status": "restored_canonical", "recovery_backup_id": recovery["id"],
        "manifest_id": store.active_manifest(), 'workflow_restored':manifest.get('workflow_state')=='included',
        "warning": "Canonical/checkpoint references verified; unfinished work remains interrupted for explicit refresh. External indexes must be verified/rebuilt."}


def restore(store:Store,backup_id:str)->dict:
    with maintenance(store):
        return _restore(store,backup_id)
