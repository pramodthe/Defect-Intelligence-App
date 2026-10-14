import json
import time
import uuid
from pathlib import Path
from threading import Lock
from contextlib import closing
from typing import Any
from collections import Counter, deque
from app.contracts import ChunkMetadata
from app.ontology import Ontology
from app.store import Store, canonical, digest, identity
from app.embeddings import embedding_provider, embedding_spec, selected_config, configured


def validate_graph(store: Store, doc_id: str, ontology: Ontology) -> dict:
    entities = store.all("SELECT * FROM entities WHERE document_id=?", (doc_id,))
    anchors = store.all("SELECT * FROM anchors WHERE document_id=?", (doc_id,))
    assertions = store.all("SELECT * FROM assertions WHERE document_id=?", (doc_id,))
    ids = {e["id"] for e in entities}
    anchor_ids = {a["id"] for a in anchors}
    nodes = [{"id": e["id"], "kind": e["kind"], "label": e["label"], "payload": json.loads(e["payload"])} for e in entities]
    nodes += [{"id": a["id"], "kind": "SourceAnchor", "label": "Source passage", "payload": {"block_id": a["block_id"]}} for a in anchors]
    edges = []
    document = store.require("SELECT * FROM documents WHERE id=?", (doc_id,))
    nodes.append({"id": doc_id, "kind": "ReportVersion", "label": document["filename"], "payload": {"authority_role": document["role"]}})
    media = store.all("SELECT * FROM media WHERE document_id=?", (doc_id,))
    for m in media:
        nodes.append({"id": m["id"], "kind": "MediaOccurrence", "label": m["caption"] or m["role"], "payload": {"identity": json.loads(m["identity_json"]), "asset_id": m["asset_id"]}})
        nodes.append({"id": m["asset_id"], "kind": "MediaAsset", "label": "Original media", "payload": {}})
        edges.append({"source": doc_id, "target": m["id"], "kind": "HAS_MEDIA_OCCURRENCE", "assertion_id": "structural:" + m["block_id"]})
        edges.append({"source": m["id"], "target": m["asset_id"], "kind": "USES_ASSET", "assertion_id": "structural:" + m["block_id"]})
        memberships=store.all('SELECT DISTINCT u.item_id FROM unit_blocks ub JOIN units u ON u.id=ub.unit_id WHERE ub.block_id=? AND u.item_id IS NOT NULL',(m['block_id'],))
        for membership in memberships:
            edges.append({'source':membership['item_id'],'target':m['id'],'kind':'SHARED_ITEM_MEDIA_CONTEXT','assertion_id':'structural:'+m['block_id']})
    chunks = latest_chunks(store,doc_id)
    for c in chunks:
        meta = json.loads(c["metadata"])
        nodes.append({"id": c["id"], "kind": "ChunkRevision", "label": c["header"], "payload": {"metadata_hash": c["metadata_hash"], "text_hash": c["text_hash"], "parent_context_id": c["parent_id"]}})
        for aid in meta["assertion_ids"]:
            if not store.one("SELECT id FROM assertions WHERE id=? AND document_id=?", (aid, doc_id)):
                raise ValueError("Invalid chunk assertion mapping")
            edges.append({"source": c["id"], "target": aid, "kind": "EVIDENCE_FOR", "assertion_id": aid})
        for concept in meta["concept_ids"]:
            definition = store.one("SELECT * FROM concepts WHERE id=?", (concept,))
            if not definition:
                raise ValueError("Unregistered concept")
            nodes.append({"id": concept, "kind": "Concept", "label": definition["label"], "payload": {"family": definition["family"], "catalog_version": definition["catalog_version"]}})
            links = store.all("SELECT assertion_id FROM chunk_links WHERE revision_id=? AND concept_id=?", (c["id"], concept))
            if not links:
                raise ValueError("Ungrounded concept mapping")
            edges.append({"source": c["id"], "target": concept, "kind": "MAPS_TO_CONCEPT", "assertion_id": links[0]["assertion_id"]})
    editions = store.all("SELECT * FROM reference_editions WHERE document_id=?", (doc_id,))
    for edition in editions:
        nodes.append({"id": edition["id"], "kind": "ReferenceEdition", "label": edition["label"], "payload": {"state": edition["state"], "part": edition["part"], "year": edition["year"], "volume": edition["volume"], "amendments": json.loads(edition["amendments"]), "synthetic": bool(edition["synthetic"])}})
        fragments = store.all("SELECT * FROM reference_fragments WHERE edition_id=?", (edition["id"],))
        for fragment in fragments:
            nodes.append({"id": fragment["id"], "kind": "ReferenceFragment", "label": fragment["identifier"], "payload": {"kind": fragment["kind"], "state": fragment["state"], "dependencies": json.loads(fragment["dependencies"])}})
            edges.append({"source": edition["id"], "target": fragment["id"], "kind": "CONTAINS_FRAGMENT", "assertion_id": "reviewed_identity:" + fragment["id"]})
            for relationship in store.all("SELECT * FROM reference_relationships WHERE from_fragment_id=?", (fragment["id"],)):
                target = store.require("SELECT * FROM reference_editions WHERE id=?", (relationship["to_edition_id"],))
                nodes.append({"id": target["id"], "kind": "ReferenceEdition", "label": target["label"], "payload": {"state": target["state"], "amendments": json.loads(target["amendments"]), "part": target["part"], "year": target["year"]}})
                nodes.append({"id": relationship["id"], "kind": "ReferenceRelationship", "label": relationship["basis"], "payload": {"state": relationship["state"], "scope": relationship["scope"], "basis": relationship["basis"], "predicates": json.loads(relationship["predicates"]), "reviewer": relationship["reviewer"]}})
                edges.append({"source": relationship["id"], "target": fragment["id"], "kind": "FROM_PROVISION", "assertion_id": relationship["id"]})
                edges.append({"source": relationship["id"], "target": target["id"], "kind": "TO_EDITION", "assertion_id": relationship["id"]})
                for support in json.loads(relationship["anchor_ids"]):
                    if support not in anchor_ids:
                        raise ValueError("Invalid original reference-chain support")
                    edges.append({"source": relationship["id"], "target": support, "kind": "SUPPORTED_BY", "assertion_id": relationship["id"]})
    for a in assertions:
        if a["predicate"] not in ontology.predicates or a["subject_id"] not in ids or a["object_id"] and a["object_id"] not in ids:
            raise ValueError("Invalid graph endpoint or governed predicate")
        supports = store.all("SELECT anchor_id FROM assertion_support WHERE assertion_id=?", (a["id"],))
        if not supports or any(s["anchor_id"] not in anchor_ids for s in supports):
            raise ValueError("Unsupported or foreign graph assertion")
        if a["predicate"] in {"references", "classified_as"} and a["kind"] in {"reported_reference", "source_supported_mapping"}:
            raise ValueError("Reported/mapped statement cannot mint normative or classification edge")
        nodes.append({"id": a["id"], "kind": "Assertion", "label": a["predicate"].replace("_", " "),
                      "payload": {"predicate": a["predicate"], "kind": a["kind"], "scope": a["scope"], "review_state": a["state"], "value": a["value"]}})
        edges.append({"source": a["id"], "target": a["subject_id"], "kind": "HAS_SUBJECT", "assertion_id": a["id"]})
        if a["object_id"]:
            edges.append({"source": a["id"], "target": a["object_id"], "kind": "HAS_OBJECT", "assertion_id": a["id"]})
        edges += [{"source": a["id"], "target": s["anchor_id"], "kind": "SUPPORTED_BY", "assertion_id": a["id"]} for s in supports]
    nodes = list({n["id"]: n for n in nodes}.values())
    node_ids = {n["id"] for n in nodes}
    if any(e["source"] not in node_ids or e["target"] not in node_ids for e in edges):
        raise ValueError("Missing construction endpoint")
    from app.domain import build_snapshot, graph_batch
    snapshot = build_snapshot(store, doc_id, ontology)
    domain = graph_batch(snapshot, ontology.domain_model)
    combined = {n['id']: n for n in domain['nodes']}
    for native in nodes:
        typed = combined.get(native['id'])
        if typed and typed['kind'] != 'OntologyClass':
            native['payload'] = {**native['payload'], 'domain': typed['payload'], 'domain_class': typed['kind']}
        combined[native['id']] = native
    edges = edges + domain['edges']
    return {'nodes':list(combined.values()),'edges':edges,'domain_snapshot_id':snapshot['id'],
            'domain_record_count':len(snapshot['records']),'domain_relation_count':len(snapshot['relations']),
            'domain_version':ontology.domain_version}


class NeoProjection:
    def __init__(self, store: Store):
        self.store = store

    def driver(self):
        from neo4j import GraphDatabase
        c = self.store.config
        return GraphDatabase.driver(c.neo4j_uri, auth=(c.neo4j_user, c.neo4j_password), connection_timeout=4)

    def write(self, revision: str, batch: dict) -> dict:
        with self.driver() as driver:
            driver.verify_connectivity()
            driver.execute_query("CREATE CONSTRAINT evidence_key IF NOT EXISTS FOR (n:Evidence) REQUIRE n.projection_key IS UNIQUE")
            for start in range(0, len(batch["nodes"]), 300):
                rows = [{**n, "key": revision + ":" + n["id"], "payload_json": canonical(n["payload"])} for n in batch["nodes"][start:start + 300]]
                driver.execute_query("UNWIND $rows AS row MERGE (n:Evidence {projection_key:row.key}) ON CREATE SET n.canonical_id=row.id,n.kind=row.kind,n.label=row.label,n.payload_json=row.payload_json,n.domain_class=coalesce(row.payload.domain_class,row.payload.class_id),n.revision=$revision", rows=rows, revision=revision)
            for start in range(0, len(batch["edges"]), 300):
                rows = [{**e, "source_key": revision + ":" + e["source"], "target_key": revision + ":" + e["target"]} for e in batch["edges"][start:start + 300]]
                driver.execute_query("UNWIND $rows AS row MATCH (s:Evidence {projection_key:row.source_key}),(t:Evidence {projection_key:row.target_key}) MERGE (s)-[r:LINK {kind:row.kind,assertion_id:row.assertion_id}]->(t)", rows=rows)
            records, _, _ = driver.execute_query("MATCH (n:Evidence {revision:$revision}) RETURN n.canonical_id AS id", revision=revision)
            actual = sorted(r["id"] for r in records)
            expected = sorted(n["id"] for n in batch["nodes"])
            if actual != expected:
                raise ValueError("Neo4j projection receipt ID mismatch")
            return {"state": "ready", "id_hash": digest(actual), "count": len(actual), "profile": "qualified-evidence/1"}

    def neighbors(self, ids: list[str], revisions: list[str], limit=100):
        with self.driver() as driver:
            records, _, _ = driver.execute_query(
                "MATCH (n:Evidence)-[e:LINK]-(m:Evidence) WHERE n.canonical_id IN $ids AND n.revision IN $revisions AND m.revision=n.revision RETURN n.canonical_id AS source,m.canonical_id AS target,e.kind AS kind,e.assertion_id AS assertion_id LIMIT $limit",
                ids=ids, revisions=revisions, limit=limit)
            return [dict(r) for r in records]

    def explore(self,ids:list[str],revisions:list[str],limit=100):
        with self.driver() as driver:
            records,_,_=driver.execute_query(
                "MATCH (seed:Evidence) WHERE seed.canonical_id IN $ids AND seed.revision IN $revisions "
                "MATCH p=(seed)-[:LINK*1..3]-(n:Evidence) WHERE ALL(m IN nodes(p) WHERE m.revision=seed.revision) "
                "AND NONE(m IN nodes(p) WHERE m.kind IN ['ReportVersion','OntologyClass','MediaAsset','ImageAsset','OriginalAsset'] AND m<>last(nodes(p))) "
                "UNWIND range(0,length(p)) AS step WITH nodes(p)[step] AS node,step "
                "WITH node,min(step) AS distance ORDER BY distance,CASE WHEN node.canonical_id IN $ids THEN 0 "
                "WHEN node.kind='DomainAssertion' THEN 1 WHEN node.kind='Assertion' THEN 2 WHEN node.kind IN ['SourceAnchor','TextPassage'] THEN 3 ELSE 4 END,node.canonical_id "
                "RETURN node.canonical_id AS id,node.kind AS kind,node.label AS label,node.payload_json AS payload LIMIT $limit",
                ids=ids,revisions=revisions,limit=limit*8+1)
            candidates={r['id']:{'id':r['id'],'kind':r['kind'],'label':r['label'],'payload':json.loads(r['payload'])} for r in records[:limit*8]}
            if not candidates:
                return {'nodes':[],'edges':[],'truncated':False,'coverage':'Neo4j qualified evidence projection · pinned manifest'}
            relationships,_,_=driver.execute_query("MATCH (n:Evidence)-[e:LINK]->(m:Evidence) WHERE n.canonical_id IN $ids AND m.canonical_id IN $ids AND n.revision IN $revisions AND m.revision=n.revision RETURN DISTINCT n.canonical_id AS source,m.canonical_id AS target,e.kind AS kind,e.assertion_id AS assertion_id LIMIT 4000",ids=list(candidates),revisions=revisions)
            adjacency: dict[str,set[str]]={key:set() for key in candidates}
            for row in relationships:
                adjacency[row['source']].add(row['target'])
                adjacency[row['target']].add(row['source'])
            # A balanced connected view keeps image-heavy reports from hiding assertions or sources.
            caps={'Assertion':max(6,limit//3),'SourceAnchor':max(4,limit//4),'ChunkRevision':max(2,limit//8),
                  'Concept':max(2,limit//10),'MediaOccurrence':max(2,limit//12),'MediaAsset':max(2,limit//12),
                  'Finding':max(2,limit//12),'ReportVersion':1,'DomainAssertion':max(6,limit//4),'OntologyClass':max(4,limit//8),'TextPassage':max(4,limit//4)}
            priority={'DomainAssertion':0,'Assertion':1,'SourceAnchor':2,'TextPassage':2,'OntologyClass':3,'ChunkRevision':5,'Concept':6,'Finding':4,'MediaOccurrence':5}
            selected=[key for key in ids if key in candidates]
            counts=Counter(candidates[key]['kind'] for key in selected)
            visited=set(selected)
            frontier=deque(selected)
            while frontier and len(selected)<limit:
                key=frontier.popleft()
                neighbors=sorted(adjacency[key],key=lambda other:(priority.get(candidates[other]['kind'],6),other))
                for other in neighbors:
                    if other in visited:
                        continue
                    visited.add(other)
                    kind=candidates[other]['kind']
                    if counts[kind]>=caps.get(kind,max(2,limit//10)):
                        continue
                    selected.append(other)
                    counts[kind]+=1
                    if kind not in {'ReportVersion','OntologyClass','MediaAsset','ImageAsset','OriginalAsset'}:
                        frontier.append(other)
                    if len(selected)==limit:
                        break
            nodes=[candidates[key] for key in selected]
            from app.domain import scope_label
            for node in nodes:
                payload=node.pop('payload')
                node['domain']=payload.get('domain') or (payload if payload.get('class_id') else None)
                if node['kind']=='OntologyClass':
                    node['definition']=payload
                if node['kind']=='DomainAssertion':
                    node['assertion']=payload
                if node['kind']=='Assertion':
                    assertion=self.store.require('SELECT * FROM assertions WHERE id=?',(node['id'],))
                    node['assertion']={**assertion,'anchor_ids':[s['anchor_id'] for s in self.store.all('SELECT anchor_id FROM assertion_support WHERE assertion_id=?',(node['id'],))]}
                if node.get('domain'):
                    node['domain']['scope_label']=scope_label(self.store,node['domain']['scope'])
                if node.get('assertion'):
                    node['assertion']['scope_label']=scope_label(self.store,node['assertion']['scope'])
            keys=set(selected)
            edges=[{'id':identity('edge',dict(r)),'source':r['source'],'target':r['target'],
                    'label':r['kind'].replace('_',' ').lower(),'assertion_id':r['assertion_id']}
                   for r in relationships if r['source'] in keys and r['target'] in keys]
            return {'nodes':nodes,'edges':edges[:200],
                    'truncated':len(records)>len(nodes) or len(edges)>200 or len(relationships)>=4000,
                    'semantic_validation':'unreviewed',
                    'coverage':'Neo4j document evidence graph · automatic semantic mappings require review · published version'}


def latest_chunks(store: Store, document_id: str):
    return store.all("SELECT c.* FROM chunk_revisions c JOIN chunks ch ON ch.id=c.chunk_id JOIN units u ON u.id=ch.unit_id JOIN documents d ON d.id=c.document_id WHERE c.document_id=? AND u.semantic_revision=d.active_semantic_revision AND c.rowid IN (SELECT MAX(rowid) FROM chunk_revisions GROUP BY chunk_id) ORDER BY c.id",(document_id,))


_embedding_models: dict[str, Any] = {}
_embedding_lock = Lock()


class LocalEmbedding:
    dimensions = 768

    def __init__(self, store: Store):
        self.store = store
        self.model: Any = None
        self.profile = "bge-base-en-v1.5/" + Path(store.config.embedding_path).name

    def query_text(self, question: str) -> str:
        return "Represent this sentence for searching relevant passages: " + question

    def encode(self, texts: list[str]):
        if not self.store.config.embedding_path:
            raise RuntimeError("Local BGE cache not configured")
        from sentence_transformers import SentenceTransformer
        from app.chunking import TokenCounter
        counter = TokenCounter(self.store.config.tokenizer_path or self.store.config.embedding_path)
        if not counter.tokenizer or any(counter.count(t) > 480 for t in texts):
            raise ValueError("Actual BGE token count required; oversized inputs cannot be truncated")
        if self.model is None:
            with _embedding_lock:
                if self.store.config.embedding_path not in _embedding_models:
                    import torch
                    torch.set_num_threads(2)
                    _embedding_models[self.store.config.embedding_path] = SentenceTransformer(self.store.config.embedding_path, local_files_only=True, device="cpu")
                self.model = _embedding_models[self.store.config.embedding_path]
        if self.model.get_embedding_dimension() != 768:
            raise ValueError("Embedding profile dimension mismatch")
        import numpy as np
        cache = self.store.root / "derived/embeddings" / digest(self.profile)[:16]
        cache.mkdir(parents=True, exist_ok=True)
        vectors: list[Any] = [None] * len(texts)
        missing = []
        for index, text in enumerate(texts):
            path = cache / (digest(text) + ".npy")
            if path.exists():
                value = np.load(path, allow_pickle=False)
                if value.shape == (768,) and np.isfinite(value).all():
                    vectors[index] = value.tolist()
                    continue
            missing.append(index)
        if missing:
            encoded = self.model.encode([texts[i] for i in missing], batch_size=16, normalize_embeddings=True, show_progress_bar=False)
            for index, vector in zip(missing, encoded, strict=True):
                path = cache / (digest(texts[index]) + ".npy")
                tmp = cache / ("tmp_" + uuid.uuid4().hex[:16])
                with tmp.open("wb") as stream:
                    np.save(stream, vector, allow_pickle=False)
                tmp.replace(path)
                vectors[index] = vector.tolist()
        return vectors


class QdrantProjection:
    def __init__(self, store: Store, embeddings=None, owner=None):
        self.store = store
        self.embeddings = embeddings or embedding_provider(store, owner)

    def client(self):
        from qdrant_client import QdrantClient
        return QdrantClient(url=self.store.config.qdrant_url, api_key=self.store.config.qdrant_key or None, timeout=8)

    def collection(self, role: str):
        # Short physical collection names avoid Windows payload-index path limits.
        return ("reports_" if role != "original_reference" else "references_") + digest([self.embeddings.profile,'payload/2'])[:20]

    def write(self, revision: str, chunks: list[dict]) -> dict:
        from qdrant_client import models
        with closing(self.client()) as client:
            role_groups: dict[str, list[dict]] = {}
            for chunk in chunks:
                meta = ChunkMetadata.model_validate_json(chunk["metadata"])
                role_groups.setdefault(meta.source_role, []).append(chunk)
            for role, records in role_groups.items():
                name = self.collection(role)
                if not client.collection_exists(name):
                    client.create_collection(name, vectors_config=models.VectorParams(size=self.embeddings.dimensions, distance=models.Distance.COSINE))
                vector_config = client.get_collection(name).config.params.vectors
                if not isinstance(vector_config, models.VectorParams) or vector_config.size != self.embeddings.dimensions:
                    raise ValueError("Qdrant collection dimension does not match its embedding profile")
                payload_schema = client.get_collection(name).payload_schema
                for field in ["projection_revision_id", "document_version_id", "source_role", "content_kind", "concept_ids", "occurrence_ids"]:
                    if field not in payload_schema:
                        client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
                for start in range(0, len(records), 32):
                    batch = records[start:start + 32]
                    vectors = self.embeddings.encode([c["retrieval_text"] for c in batch])
                    points = []
                    for c, vector in zip(batch, vectors, strict=True):
                        meta = json.loads(c["metadata"])
                        payload = {k: meta[k] for k in ["chunk_revision_id", "document_version_id", "source_role", "content_kind", "concept_ids", "occurrence_ids", "media_occurrence_ids", "logical_unit_id", "defect_item_id"]}
                        payload.update({"projection_revision_id": revision, "metadata_hash": c["metadata_hash"],
                            "retrieval_text_hash": c["text_hash"], "embedding_profile_id": self.embeddings.profile})
                        pid = str(uuid.uuid5(uuid.NAMESPACE_URL, revision + c["id"] + self.embeddings.profile))
                        points.append(models.PointStruct(id=pid, vector=vector, payload=payload))
                    client.upsert(name, points, wait=True)
                actual: list[str] = []
                offset = None
                while True:
                    points, offset = client.scroll(name, scroll_filter=models.Filter(must=[models.FieldCondition(key="projection_revision_id", match=models.MatchValue(value=revision))]), limit=200, offset=offset, with_payload=True)
                    actual.extend(p.payload["chunk_revision_id"] for p in points)
                    if offset is None:
                        break
                if sorted(actual) != sorted(c["id"] for c in records):
                    raise ValueError("Qdrant receipt ID mismatch")
            return {"state": "ready", "count": len(chunks), "id_hash": digest(sorted(c["id"] for c in chunks)),
                    "profile": self.embeddings.profile, "dimensions": self.embeddings.dimensions}

    def search(self, question: str, revisions: list[str], limit=30):
        from qdrant_client import models
        vector = self.embeddings.encode([self.embeddings.query_text(question)])[0]
        results: list[dict] = []
        with closing(self.client()) as client:
            for role in ["company_report", "original_reference"]:
                name = self.collection(role)
                if client.collection_exists(name):
                    points = client.query_points(name, query=vector, query_filter=models.Filter(must=[
                        models.FieldCondition(key="projection_revision_id", match=models.MatchAny(any=revisions)),
                        models.FieldCondition(key="embedding_profile_id", match=models.MatchValue(value=self.embeddings.profile))]), limit=limit).points
                    results.extend({"id": p.payload["chunk_revision_id"], "score": p.score,
                        "metadata_hash": p.payload["metadata_hash"], "text_hash": p.payload["retrieval_text_hash"]} for p in points)
        return sorted(results, key=lambda r: -r["score"])[:limit]


def stage(store: Store, document_id: str, ontology: Ontology, graph=None, vectors=None, embedding_owner=None) -> dict:
    from app import visual_embeddings as visual
    chunks = latest_chunks(store,document_id)
    graph_batch = validate_graph(store, document_id, ontology)
    spec = embedding_spec(selected_config(store))
    embedding_profile = [vectors.embeddings.profile if vectors and hasattr(vectors, 'embeddings') else spec.profile,
                         'payload/2'] if configured(store) or vectors else "unconfigured"
    visual_config = visual.selected_config(store)
    visual_profile = visual.spec(visual_config)
    visual_records = visual.media_records(store, document_id) if visual.configured(store) else []
    visual_snapshot = [visual_profile.profile, visual.source_identity(visual_records)] if visual.configured(store) else None
    revision_parts = [document_id, [(c["id"], c["metadata_hash"], c["text_hash"]) for c in chunks], digest(graph_batch), embedding_profile, ontology.version, "projection/1"]
    revision = identity("projection", *revision_parts, *([visual_snapshot] if visual_snapshot else []))
    for c in chunks:
        ChunkMetadata.model_validate_json(c["metadata"])
        if digest(json.loads(c["metadata"])) != c["metadata_hash"] or digest(c["retrieval_text"]) != c["text_hash"]:
            raise ValueError("Canonical chunk checksum mismatch")
    receipts = {}
    receipts['domain'] = {'state':'ready','snapshot_id':graph_batch['domain_snapshot_id'],
                          'ontology_version':graph_batch['domain_version'],
                          'records':graph_batch['domain_record_count'],'relationships':graph_batch['domain_relation_count']}
    # Transactional FTS stage; manifest-scoped joins hide staged rows from readers.
    with store.connect() as con:
        for c in chunks:
            if not con.execute("SELECT rowid FROM chunks_fts WHERE revision_id=?", (c["id"],)).fetchone():
                refs = json.loads(c["metadata"])["cited_reference_ids"]
                labels = [store.require("SELECT label FROM references_catalog WHERE id=?", (r,))["label"] for r in refs]
                con.execute("INSERT INTO chunks_fts(revision_id,text,title,identifiers) VALUES(?,?,?,?)", (c["id"], c["raw_body"], c["header"], " ".join(labels)))
        actual = [r[0] for r in con.execute("SELECT revision_id FROM chunks_fts WHERE revision_id IN (" + ",".join("?" for _ in chunks) + ")",[c["id"] for c in chunks])]
        if sorted(actual) != sorted(c["id"] for c in chunks):
            raise ValueError("FTS receipt mismatch")
    receipts["fts"] = {"state": "ready", "count": len(actual), "id_hash": digest(sorted(actual))}
    if graph or store.config.neo4j_uri:
        receipts["graph"] = (graph or NeoProjection(store)).write(revision, graph_batch)
    else:
        receipts["graph"] = {"state": "unconfigured", "canonical_batch_hash": digest(graph_batch)}
    if vectors or store.config.qdrant_url and configured(store):
        receipts["vectors"] = (vectors or QdrantProjection(store, owner=embedding_owner)).write(revision, chunks)
    else:
        receipts["vectors"] = {"state": "unconfigured", "reason": "Qdrant and the selected embedding provider must be configured"}
    if visual_config.visual_embedding_enabled and visual_profile.provider != 'disabled':
        if not visual.configured(store) or not store.config.qdrant_url:
            raise ValueError('Visual embeddings selected: configure and test the endpoint before publishing a new index')
        receipts['visuals'] = visual.VisualProjection(store, owner=embedding_owner).write(revision, visual_records)
    profile = "full" if all(receipts[k]["state"] == "ready" for k in receipts) else "partial_source_lexical"
    store.insert("projections", {"id": revision, "document_id": document_id, "profile": profile,
        "state": "validated", "chunk_ids": [c["id"] for c in chunks], "receipts": receipts, "created": time.time()})
    return {"projection_id": revision, "profile": profile, "receipts": receipts}
