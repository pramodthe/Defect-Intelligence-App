import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.settings import Settings


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    data = value if isinstance(value, bytes) else canonical(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def identity(kind: str, *parts: Any) -> str:
    return kind + "_" + digest(parts)[:32]


def new_id(kind: str) -> str:
    return kind + "_" + uuid.uuid4().hex


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS domain_snapshots(id TEXT PRIMARY KEY,document_id TEXT NOT NULL,
 ontology_version TEXT NOT NULL,source_semantic TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,sha256 TEXT UNIQUE NOT NULL,path TEXT NOT NULL,
 mime TEXT NOT NULL,size INTEGER NOT NULL,metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS families(id TEXT PRIMARY KEY,label TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,family_id TEXT NOT NULL REFERENCES families(id),
 asset_id TEXT NOT NULL REFERENCES assets(id),sha256 TEXT UNIQUE NOT NULL,filename TEXT NOT NULL,
 role TEXT NOT NULL,status TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,
 metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS structures(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),
 ir_asset_id TEXT NOT NULL REFERENCES assets(id),profile TEXT NOT NULL,hash TEXT NOT NULL,state TEXT NOT NULL,
 UNIQUE(id,document_id));
CREATE TABLE IF NOT EXISTS blocks(id TEXT PRIMARY KEY,document_id TEXT NOT NULL,structure_id TEXT NOT NULL,
 parent_id TEXT,kind TEXT NOT NULL,sequence INTEGER NOT NULL,text TEXT NOT NULL,content_kind TEXT NOT NULL,
 locator TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(id,document_id),
 FOREIGN KEY(structure_id,document_id) REFERENCES structures(id,document_id),
 FOREIGN KEY(parent_id,document_id) REFERENCES blocks(id,document_id));
CREATE INDEX IF NOT EXISTS blocks_doc ON blocks(document_id,sequence);
CREATE TABLE IF NOT EXISTS anchors(id TEXT PRIMARY KEY,block_id TEXT NOT NULL,document_id TEXT NOT NULL,
 start_cp INTEGER NOT NULL,end_cp INTEGER NOT NULL,quote_hash TEXT NOT NULL,
 FOREIGN KEY(block_id,document_id) REFERENCES blocks(id,document_id),UNIQUE(id,document_id));
CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,asset_id TEXT NOT NULL REFERENCES assets(id),
 document_id TEXT NOT NULL REFERENCES documents(id),block_id TEXT NOT NULL,caption TEXT NOT NULL,
 role TEXT NOT NULL,identity_json TEXT NOT NULL,warnings TEXT NOT NULL,
 FOREIGN KEY(block_id,document_id) REFERENCES blocks(id,document_id));
CREATE INDEX IF NOT EXISTS media_doc ON media(document_id);
CREATE TABLE IF NOT EXISTS visuals(id TEXT PRIMARY KEY,media_id TEXT NOT NULL REFERENCES media(id),
 text TEXT NOT NULL,regions TEXT NOT NULL,method TEXT NOT NULL,profile TEXT NOT NULL,warnings TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),
 title TEXT NOT NULL,heading_anchor_id TEXT REFERENCES anchors(id),UNIQUE(id,document_id));
CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY,item_id TEXT NOT NULL,document_id TEXT NOT NULL,
 identifier TEXT NOT NULL,location TEXT NOT NULL,anchor_id TEXT NOT NULL REFERENCES anchors(id),
 scope_state TEXT NOT NULL,FOREIGN KEY(item_id,document_id) REFERENCES items(id,document_id));
CREATE INDEX IF NOT EXISTS findings_identifier ON findings(document_id,identifier);
CREATE TABLE IF NOT EXISTS finding_equivalences(id TEXT PRIMARY KEY,
 canonical_finding_id TEXT NOT NULL REFERENCES findings(id),alias_finding_id TEXT UNIQUE NOT NULL REFERENCES findings(id),
 anchor_ids TEXT NOT NULL,reviewer TEXT NOT NULL,reason TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS parents(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),
 text TEXT NOT NULL,block_ids TEXT NOT NULL,dependencies TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS units(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),
 structure_id TEXT NOT NULL REFERENCES structures(id),semantic_revision TEXT NOT NULL,kind TEXT NOT NULL,
 purpose TEXT NOT NULL,item_id TEXT REFERENCES items(id),finding_id TEXT REFERENCES findings(id),
 option_id TEXT,parent_id TEXT NOT NULL REFERENCES parents(id),scope_state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS unit_blocks(unit_id TEXT NOT NULL REFERENCES units(id),
 block_id TEXT NOT NULL REFERENCES blocks(id),sequence INTEGER NOT NULL,PRIMARY KEY(unit_id,sequence));
CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id),
 kind TEXT NOT NULL,label TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS concepts(id TEXT PRIMARY KEY,family TEXT NOT NULL,label TEXT NOT NULL,
 definition TEXT NOT NULL,aliases TEXT NOT NULL,catalog_version TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assertions(id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id),
 subject_id TEXT NOT NULL REFERENCES entities(id),predicate TEXT NOT NULL,object_id TEXT REFERENCES entities(id),
 value TEXT,kind TEXT NOT NULL,scope TEXT NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL,
 predecessor_id TEXT REFERENCES assertions(id),payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assertion_support(assertion_id TEXT NOT NULL REFERENCES assertions(id),
 anchor_id TEXT NOT NULL REFERENCES anchors(id),PRIMARY KEY(assertion_id,anchor_id));
CREATE TABLE IF NOT EXISTS mentions(id TEXT PRIMARY KEY,block_id TEXT NOT NULL REFERENCES blocks(id),
 start_cp INTEGER NOT NULL,end_cp INTEGER NOT NULL,concept_id TEXT REFERENCES concepts(id),
 entity_id TEXT REFERENCES entities(id),method TEXT NOT NULL,state TEXT NOT NULL,catalog_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS options(id TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES items(id),
 title TEXT NOT NULL,parent_id TEXT NOT NULL REFERENCES parents(id),alternative_group TEXT,state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS work_events(id TEXT PRIMARY KEY,item_id TEXT REFERENCES items(id),
 kind TEXT NOT NULL,anchor_id TEXT NOT NULL REFERENCES anchors(id),payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,unit_id TEXT NOT NULL REFERENCES units(id),
 content_kind TEXT NOT NULL,profile TEXT NOT NULL,source_identity_hash TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS chunk_revisions(id TEXT PRIMARY KEY,chunk_id TEXT NOT NULL REFERENCES chunks(id),
 document_id TEXT NOT NULL REFERENCES documents(id),parent_id TEXT NOT NULL REFERENCES parents(id),
 raw_body TEXT NOT NULL,header TEXT NOT NULL,retrieval_text TEXT NOT NULL,text_hash TEXT NOT NULL,
 metadata TEXT NOT NULL,metadata_hash TEXT NOT NULL,token_count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS chunk_segments(revision_id TEXT NOT NULL REFERENCES chunk_revisions(id),
 sequence INTEGER NOT NULL,block_id TEXT NOT NULL REFERENCES blocks(id),start_cp INTEGER NOT NULL,
 end_cp INTEGER NOT NULL,role TEXT NOT NULL,CHECK(start_cp>=0 AND end_cp>start_cp),PRIMARY KEY(revision_id,sequence));
CREATE TABLE IF NOT EXISTS chunk_links(revision_id TEXT NOT NULL REFERENCES chunk_revisions(id),
 concept_id TEXT NOT NULL REFERENCES concepts(id),assertion_id TEXT NOT NULL REFERENCES assertions(id),
 role TEXT NOT NULL,catalog_version TEXT NOT NULL,PRIMARY KEY(revision_id,concept_id,assertion_id));
CREATE TABLE IF NOT EXISTS chunk_assertions(revision_id TEXT NOT NULL REFERENCES chunk_revisions(id),
 assertion_id TEXT NOT NULL REFERENCES assertions(id),role TEXT NOT NULL,PRIMARY KEY(revision_id,assertion_id));
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(revision_id UNINDEXED,text,title,identifiers,
 tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS references_catalog(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),
 anchor_id TEXT NOT NULL REFERENCES anchors(id),label TEXT NOT NULL,normalized TEXT NOT NULL,
 identity_json TEXT NOT NULL,state TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS references_exact ON references_catalog(normalized);
CREATE TABLE IF NOT EXISTS reference_editions(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),
 label TEXT NOT NULL,family TEXT NOT NULL,part TEXT,year TEXT NOT NULL,volume TEXT,amendments TEXT NOT NULL,
 state TEXT NOT NULL,reviewer TEXT NOT NULL,anchor_ids TEXT NOT NULL,identity_hash TEXT UNIQUE NOT NULL,synthetic INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS reference_fragments(id TEXT PRIMARY KEY,edition_id TEXT NOT NULL REFERENCES reference_editions(id),
 kind TEXT NOT NULL,identifier TEXT NOT NULL,anchor_ids TEXT NOT NULL,dependencies TEXT NOT NULL,state TEXT NOT NULL,
 UNIQUE(edition_id,kind,identifier));
CREATE TABLE IF NOT EXISTS reference_relationships(id TEXT PRIMARY KEY,from_fragment_id TEXT NOT NULL REFERENCES reference_fragments(id),
 to_edition_id TEXT NOT NULL REFERENCES reference_editions(id),basis TEXT NOT NULL,scope TEXT NOT NULL,predicates TEXT NOT NULL,
 anchor_ids TEXT NOT NULL,reviewer TEXT NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS demands(id TEXT PRIMARY KEY,label TEXT NOT NULL,identity_json TEXT NOT NULL,
 state TEXT NOT NULL,origin_reference_id TEXT NOT NULL REFERENCES references_catalog(id));
CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,label TEXT NOT NULL,version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS parts(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),label TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contexts(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
 part_id TEXT REFERENCES parts(id),purpose TEXT NOT NULL,version INTEGER NOT NULL,facts TEXT NOT NULL,
 created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,context_id TEXT,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id),
 assertion_id TEXT REFERENCES assertions(id),kind TEXT NOT NULL,message TEXT NOT NULL,anchor_ids TEXT NOT NULL,
 state TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audits(id TEXT PRIMARY KEY,review_id TEXT REFERENCES reviews(id),
 predecessor_id TEXT,successor_id TEXT,reason TEXT NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),
 status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,lease_owner TEXT,lease_until REAL,
 cancel INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,graph_version TEXT NOT NULL,error TEXT,
 UNIQUE(document_id,graph_version));
CREATE TABLE IF NOT EXISTS events(owner_id TEXT NOT NULL,sequence INTEGER NOT NULL,type TEXT NOT NULL,
 created REAL NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(owner_id,sequence));
CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,node TEXT NOT NULL,
 input_hash TEXT NOT NULL,state TEXT NOT NULL,tool_cost INTEGER NOT NULL,seconds_reserved REAL NOT NULL,
 result TEXT,started REAL NOT NULL,finished REAL,UNIQUE(owner_id,node,input_hash));
CREATE TABLE IF NOT EXISTS budgets(owner_id TEXT PRIMARY KEY,tools INTEGER NOT NULL DEFAULT 0,
 seconds REAL NOT NULL DEFAULT 0,rounds INTEGER NOT NULL DEFAULT 0,tokens INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL,cancel INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS projections(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),
 profile TEXT NOT NULL,state TEXT NOT NULL,chunk_ids TEXT NOT NULL,receipts TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS manifests(id TEXT PRIMARY KEY,created REAL NOT NULL,capabilities TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS manifest_members(manifest_id TEXT NOT NULL REFERENCES manifests(id),
 document_id TEXT NOT NULL REFERENCES documents(id),projection_id TEXT NOT NULL REFERENCES projections(id),
 PRIMARY KEY(manifest_id,document_id));
CREATE TABLE IF NOT EXISTS workspace(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,client_id TEXT UNIQUE NOT NULL,question TEXT NOT NULL,
 mode TEXT NOT NULL,project_id TEXT,part_id TEXT,initial_context_id TEXT,final_context_id TEXT,
 manifest_id TEXT NOT NULL REFERENCES manifests(id),graph_version TEXT NOT NULL,status TEXT NOT NULL,
 stale INTEGER NOT NULL DEFAULT 0,cancel INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,
 evidence TEXT NOT NULL,answer TEXT NOT NULL,error TEXT,checkpoint_id TEXT,
 rule_pack_ids TEXT NOT NULL DEFAULT '[]',ontology_version TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS run_dependencies(run_id TEXT NOT NULL REFERENCES runs(id),
 dependency_id TEXT NOT NULL,PRIMARY KEY(run_id,dependency_id));
CREATE TABLE IF NOT EXISTS run_drafting(run_id TEXT PRIMARY KEY REFERENCES runs(id),
 version INTEGER NOT NULL DEFAULT 1,facts TEXT NOT NULL DEFAULT '{}',
 pending_response TEXT,decision_id TEXT,conversation TEXT NOT NULL DEFAULT '[]',clarification TEXT);
"""


class Store:
    def __init__(self, config: Settings):
        self.config = config
        self.root = config.workspace_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = config.db_path

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=15000")
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self):
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            columns = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
            for name, definition in [("rule_pack_ids", "TEXT NOT NULL DEFAULT '[]'"), ("ontology_version", "TEXT NOT NULL DEFAULT ''")]:
                if name not in columns:
                    con.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
            drafting_columns = {r[1] for r in con.execute('PRAGMA table_info(run_drafting)')}
            for name, definition in [('conversation', "TEXT NOT NULL DEFAULT '[]'"), ('clarification', 'TEXT')]:
                if name not in drafting_columns:
                    con.execute(f'ALTER TABLE run_drafting ADD COLUMN {name} {definition}')
            doc_columns = {r[1] for r in con.execute("PRAGMA table_info(documents)")}
            if "active_semantic_revision" not in doc_columns:
                con.execute("ALTER TABLE documents ADD COLUMN active_semantic_revision TEXT")
            con.execute("UPDATE documents SET active_semantic_revision=(SELECT semantic_revision FROM units WHERE document_id=documents.id ORDER BY rowid DESC LIMIT 1) WHERE active_semantic_revision IS NULL")
            manifest = identity("manifest", "empty/1")
            con.execute("INSERT OR IGNORE INTO manifests VALUES(?,?,?)", (manifest, time.time(), "{}"))
            con.execute("INSERT OR IGNORE INTO workspace VALUES('manifest',?)", (manifest,))

    def all(self, sql: str, params=()) -> list[dict]:
        with self.connect() as con:
            return [dict(row) for row in con.execute(sql, params)]

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def require(self, sql: str, params=()) -> dict:
        row = self.one(sql, params)
        if row is None:
            raise KeyError("Required canonical record unavailable")
        return row

    def execute(self, sql: str, params=()):
        with self.connect() as con:
            return con.execute(sql, params).rowcount

    def insert(self, table: str, record: dict, con=None):
        # Table/column names originate exclusively from application code.
        sql = f"INSERT OR IGNORE INTO {table} ({','.join(record)}) VALUES ({','.join('?' for _ in record)})"
        values = tuple(canonical(v) if isinstance(v, (dict, list)) else v for v in record.values())
        if con is not None:
            con.execute(sql, values)
        else:
            self.execute(sql, values)

    def asset(self, data: bytes, mime: str, category="media", metadata=None) -> str:
        sha = digest(data)
        asset_id = "asset_" + sha
        existing = self.one("SELECT id FROM assets WHERE id=?", (asset_id,))
        if existing:
            return asset_id
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "application/pdf": ".pdf",
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                  "application/json": ".json", "image/tiff": ".tif", "image/gif": ".gif"}.get(mime, ".bin")
        relative = Path(category) / sha[:2] / (sha + suffix)
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            tmp = target.with_suffix(suffix + ".tmp." + uuid.uuid4().hex)
            tmp.write_bytes(data)
            tmp.replace(target)
        self.insert("assets", {"id": asset_id, "sha256": sha, "path": relative.as_posix(), "mime": mime,
                               "size": len(data), "metadata": metadata or {}})
        return asset_id

    def asset_path(self, asset_id: str) -> Path:
        asset = self.one("SELECT * FROM assets WHERE id=?", (asset_id,))
        if not asset:
            raise KeyError("Unknown managed asset")
        path = (self.root / asset["path"]).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise KeyError("Unavailable managed asset")
        return path

    def event(self, owner: str, kind: str, payload: dict):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            sequence = con.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE owner_id=?", (owner,)).fetchone()[0]
            con.execute("INSERT INTO events VALUES(?,?,?,?,?)", (owner, sequence, kind, time.time(), canonical(payload)))

    def active_manifest(self) -> str:
        return self.require("SELECT value FROM workspace WHERE key='manifest'")["value"]

    def reserve(self, owner: str, node: str, inputs: Any, tools=0, allowance=5.0) -> dict:
        op_id = identity("operation", owner, node, inputs)
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            cached = con.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone()
            if cached:
                return dict(cached)
            con.execute("INSERT OR IGNORE INTO budgets(owner_id,created) VALUES(?,?)", (owner, time.time()))
            budget = con.execute("SELECT * FROM budgets WHERE owner_id=?", (owner,)).fetchone()
            is_job = owner.startswith("job_")
            ceiling = self.config.ingest_seconds if is_job else self.config.active_seconds
            if budget["cancel"] or time.time() - budget["created"] > 86400:
                raise RuntimeError("cancelled or overall lifetime exhausted")
            if (not is_job and budget["tools"] + tools > self.config.tool_limit) or budget["seconds"] + allowance > ceiling:
                raise RuntimeError("cumulative budget exhausted")
            con.execute("UPDATE budgets SET tools=tools+?,seconds=seconds+? WHERE owner_id=?", (tools, allowance, owner))
            con.execute("INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (op_id, owner, node, digest(inputs), "reserved", tools, allowance, None, time.time(), None))
        return self.require("SELECT * FROM operations WHERE id=?", (op_id,))

    def complete_operation(self, op: dict, result: dict):
        elapsed = max(0.001, time.time() - op["started"])
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT state FROM operations WHERE id=?", (op["id"],)).fetchone()
            if current[0] == "complete":
                return
            # Crashed reservations stay charged; completed local work uses measured active time.
            con.execute("UPDATE budgets SET seconds=MAX(0,seconds-?)+? WHERE owner_id=?",
                        (op["seconds_reserved"], elapsed, op["owner_id"]))
            con.execute("UPDATE operations SET state='complete',result=?,finished=? WHERE id=?",
                        (canonical(result), time.time(), op["id"]))

    def activate(self, projection_id: str, capabilities: dict) -> str:
        projection = self.one("SELECT * FROM projections WHERE id=? AND state='validated'", (projection_id,))
        if not projection:
            raise ValueError("Unvalidated projection cannot publish")
        capabilities={**capabilities,'identity_reviews':[r['id'] for r in self.all("SELECT id FROM finding_equivalences WHERE state='confirmed' ORDER BY id")]}
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            old = con.execute("SELECT value FROM workspace WHERE key='manifest'").fetchone()[0]
            members = {r["document_id"]: r["projection_id"] for r in con.execute(
                "SELECT * FROM manifest_members WHERE manifest_id=?", (old,))}
            members[projection["document_id"]] = projection_id
            archived = {r[0] for r in con.execute("SELECT id FROM documents WHERE archived=1")}
            members = {k: v for k, v in members.items() if k not in archived}
            mid = identity("manifest", members, capabilities)
            con.execute("INSERT OR IGNORE INTO manifests VALUES(?,?,?)", (mid, time.time(), canonical(capabilities)))
            for doc, pid in members.items():
                con.execute("INSERT OR IGNORE INTO manifest_members VALUES(?,?,?)", (mid, doc, pid))
            con.execute("UPDATE workspace SET value=? WHERE key='manifest'", (mid,))
        return mid

    def activate_reindex(self, members: dict[str, str], expected_manifest: str, capabilities: dict,
                         event_id: str | None = None, event_payload: dict | None = None) -> str:
        """Publish an entire embedding rebuild together, only against its original snapshot."""
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT value FROM workspace WHERE key='manifest'").fetchone()[0]
            if current != expected_manifest:
                raise ValueError("Source library changed during rebuild; rebuild again against the current library")
            old_docs = {r[0] for r in con.execute("SELECT document_id FROM manifest_members WHERE manifest_id=?", (current,))}
            if set(members) != old_docs:
                raise ValueError("Rebuild must cover every published document")
            for doc, pid in members.items():
                if not con.execute("SELECT id FROM projections WHERE id=? AND document_id=? AND state='validated'", (pid, doc)).fetchone():
                    raise ValueError("Unvalidated projection cannot publish")
            capabilities = {**capabilities, "identity_reviews": [r[0] for r in con.execute(
                "SELECT id FROM finding_equivalences WHERE state='confirmed' ORDER BY id")]}
            mid = identity("manifest", members, capabilities)
            con.execute("INSERT OR IGNORE INTO manifests VALUES(?,?,?)", (mid, time.time(), canonical(capabilities)))
            for doc, pid in members.items():
                con.execute("INSERT OR IGNORE INTO manifest_members VALUES(?,?,?)", (mid, doc, pid))
            con.execute("UPDATE workspace SET value=? WHERE key='manifest'", (mid,))
            if event_id:
                con.execute("UPDATE outbox SET state='complete',payload=? WHERE id=?",
                            (canonical({**(event_payload or {}), "published_manifest": mid}), event_id))
        return mid

    def archive(self, doc_id: str):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("UPDATE documents SET archived=1 WHERE id=?", (doc_id,))
            old = con.execute("SELECT value FROM workspace WHERE key='manifest'").fetchone()[0]
            members = [dict(r) for r in con.execute("SELECT * FROM manifest_members WHERE manifest_id=? AND document_id<>?", (old, doc_id))]
            mid = identity("manifest", "archive", old, doc_id)
            caps = con.execute("SELECT capabilities FROM manifests WHERE id=?", (old,)).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO manifests VALUES(?,?,?)", (mid, time.time(), caps))
            for member in members:
                con.execute("INSERT OR IGNORE INTO manifest_members VALUES(?,?,?)", (mid, member["document_id"], member["projection_id"]))
            con.execute("UPDATE workspace SET value=? WHERE key='manifest'", (mid,))
            con.execute("UPDATE runs SET stale=1 WHERE id IN (SELECT run_id FROM run_dependencies WHERE dependency_id=?)", (doc_id,))
