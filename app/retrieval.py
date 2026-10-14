import json
import re
from app.extraction import reference_mentions
from app.ontology import Ontology
from app.projections import QdrantProjection
from app.store import Store, identity
from app.embeddings import configured, embedding_spec, selected_config


def manifest_chunks(store: Store, manifest: str):
    projections = store.all("SELECT p.* FROM manifest_members m JOIN projections p ON p.id=m.projection_id WHERE m.manifest_id=?", (manifest,))
    return sorted({cid for p in projections for cid in json.loads(p["chunk_ids"])}), projections


def rrf(rankings: list[list[str]], k=60):
    scores: dict[str, float] = {}
    for ranking in rankings:
        for index, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0) + 1 / (k + index + 1)
    return sorted(scores, key=lambda x: (-scores[x], x))


def search(store: Store, ontology: Ontology, query: str, manifest: str | None = None, limit=30,
           document_id: str | None = None, content_kind: str | None = None):
    manifest = manifest or store.active_manifest()
    ids, projections = manifest_chunks(store, manifest)
    if not ids:
        return {"items": [], "manifest_id": manifest, "coverage": "empty", "warnings": ["Import and publish sources first"]}
    clauses = "c.id IN (" + ",".join("?" for _ in ids) + ")"
    params = list(ids)
    if document_id:
        clauses += " AND c.document_id=?"
        params.append(document_id)
    if content_kind:
        clauses += " AND json_extract(c.metadata,'$.content_kind')=?"
        params.append(content_kind)
    all_records = store.all("SELECT c.* FROM chunk_revisions c WHERE " + clauses, params)
    allowed = {r["id"] for r in all_records}
    tokens = re.findall(r"[\w]+", query.lower())[:30]
    match = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
    lexical = store.all("SELECT c.id,bm25(chunks_fts) rank FROM chunks_fts JOIN chunk_revisions c ON c.id=chunks_fts.revision_id WHERE chunks_fts MATCH ? AND " + clauses + " ORDER BY rank LIMIT 100", [match, *params]) if match else []
    ranked_lexical = [r["id"] for r in lexical]
    normalized = re.sub(r"[^a-z0-9]", "", query.lower())
    exact = [r["id"] for r in all_records if normalized and normalized in re.sub(r"[^a-z0-9]", "", r["retrieval_text"].lower())]
    concepts = ontology.resolve(query, query)
    concept_ids = [c["id"] for c in concepts]
    mapped = store.all("SELECT DISTINCT revision_id FROM chunk_links WHERE concept_id IN (" + ",".join("?" for _ in concept_ids) + ")", concept_ids) if concept_ids else []
    mapped_ids = [r["revision_id"] for r in mapped if r["revision_id"] in allowed]
    vector_ids = []
    warnings = []
    if store.config.qdrant_url and configured(store):
        try:
            profile = embedding_spec(selected_config(store)).profile
            matching = [p["id"] for p in projections if json.loads(p["receipts"]).get("vectors", {}).get("profile") == profile]
            if len(matching) != len(projections):
                warnings.append("Embedding provider changed: rebuild the search index for complete semantic coverage")
            candidates = QdrantProjection(store).search(query, matching) if matching else []
            for c in candidates:
                original = next((r for r in all_records if r["id"] == c["id"]), None)
                if original and original["metadata_hash"] == c["metadata_hash"] and original["text_hash"] == c["text_hash"]:
                    vector_ids.append(c["id"])
                else:
                    warnings.append("Stale vector payload rejected")
        except Exception:
            warnings.append("Semantic service unavailable; exact/keyword/catalog search only")
    else:
        warnings.append("Semantic search unavailable: Qdrant or selected embedding provider unconfigured")
    fused = exact + [cid for cid in rrf([ranked_lexical, vector_ids, mapped_ids]) if cid not in exact]
    records = {r["id"]: r for r in all_records}
    results = []
    for cid in fused[:limit]:
        c = records[cid]
        meta = json.loads(c["metadata"])
        segments = store.all("SELECT s.*,a.id anchor_id FROM chunk_segments s JOIN anchors a ON a.block_id=s.block_id WHERE s.revision_id=? ORDER BY s.sequence", (cid,))
        parent = store.require("SELECT * FROM parents WHERE id=?", (c["parent_id"],))
        methods = [name for name, ranking in [("exact", exact), ("bm25", ranked_lexical), ("semantic", vector_ids), ("governed_concept", mapped_ids)] if cid in ranking]
        results.append({"id": cid, "document_id": c["document_id"], "text": c["raw_body"], "header": c["header"],
            "text_kind": meta["content_kind"], "metadata": meta, "anchor_ids": sorted({s["anchor_id"] for s in segments}),
            "segments": segments, "parent_text": parent["text"], "parent_id": parent["id"], "retrieval_methods": methods,
            "manifest_id": manifest, "authority_role": meta["authority_role"], "review_state": meta["extraction_review_state"]})
    pending = store.require("SELECT COUNT(*) n FROM documents WHERE archived=0 AND status NOT IN ('ready','partial','awaiting_configuration')")["n"]
    return {"items": results, "manifest_id": manifest, "coverage": "partial", "unprocessed_sources": pending,
            "warnings": warnings, "concept_candidates": concepts, "total_candidates": len(fused)}


def source(store: Store, anchor_id: str):
    a = store.one("SELECT a.*,b.text,b.kind,b.content_kind,b.locator,b.payload,d.filename,d.asset_id FROM anchors a JOIN blocks b ON b.id=a.block_id JOIN documents d ON d.id=a.document_id WHERE a.id=?", (anchor_id,))
    if not a:
        raise KeyError("Unknown source anchor")
    a["quote"] = a["text"][a["start_cp"]:a["end_cp"]]
    for k in ["locator", "payload"]:
        a[k] = json.loads(a[k])
    a["media"] = store.all("SELECT m.* FROM media m WHERE m.block_id=? OR m.block_id IN (SELECT id FROM blocks WHERE parent_id=?)", (a["block_id"], a["block_id"]))
    if a["payload"].get("media_occurrence_id"):
        a["media"] += store.all("SELECT * FROM media WHERE id=?", (a["payload"]["media_occurrence_id"],))
    parent = store.one("SELECT parent_id FROM blocks WHERE id=?", (a["block_id"],))
    table_id = None
    while parent and parent["parent_id"]:
        parent = store.one("SELECT id,parent_id,kind FROM blocks WHERE id=?", (parent["parent_id"],))
        if parent and parent["kind"] == "table":
            table_id = parent["id"]
            break
    a["context_blocks"] = store.all("WITH RECURSIVE children(id) AS (SELECT ? UNION ALL SELECT b.id FROM blocks b JOIN children c ON b.parent_id=c.id) SELECT b.id,b.text,b.kind,b.locator FROM blocks b JOIN children c ON b.id=c.id WHERE b.text<>'' ORDER BY b.sequence", (table_id,)) if table_id else []
    return a


def media_detail(store: Store, media_id: str):
    m = store.one("SELECT m.*,b.locator,d.filename FROM media m JOIN blocks b ON b.id=m.block_id JOIN documents d ON d.id=m.document_id WHERE m.id=?", (media_id,))
    if not m:
        raise KeyError("Unknown media occurrence")
    m["identity"] = json.loads(m.pop("identity_json"))
    m["warnings"] = json.loads(m["warnings"])
    m["locator"] = json.loads(m["locator"])
    m["original_url"] = "/api/assets/" + m["asset_id"] + "/content"
    m["visuals"] = store.all("SELECT * FROM visuals WHERE media_id=?", (media_id,))
    m["units"] = store.all("SELECT u.* FROM units u JOIN unit_blocks ub ON ub.unit_id=u.id WHERE ub.block_id=?", (m["block_id"],))
    item_ids = sorted({u["item_id"] for u in m["units"] if u["item_id"]})
    m["reasoning"] = []
    for iid in item_ids:
        rows = store.all("SELECT u.id,u.purpose,p.text,p.block_ids FROM units u JOIN parents p ON p.id=u.parent_id WHERE u.item_id=? AND u.purpose IN ('reasoning','remediation') AND u.finding_id IS NULL", (iid,))
        for r in rows:
            r["anchor_ids"] = [a["id"] for bid in json.loads(r.pop("block_ids")) for a in store.all("SELECT id FROM anchors WHERE block_id=?", (bid,))]
        m["reasoning"] += rows
    return m


def evidence_media(store: Store, ontology: Ontology, query: str, manifest=None, limit=30, offset=0, role=None):
    from app import visual_embeddings as visual
    manifest = manifest or store.active_manifest()
    members = store.all("SELECT document_id FROM manifest_members WHERE manifest_id=?", (manifest,))
    docs = {r["document_id"] for r in members}
    rows = store.all("SELECT m.*,COALESCE((SELECT group_concat(v.text,' ') FROM visuals v WHERE v.media_id=m.id),'') ocr,b.locator FROM media m JOIN blocks b ON b.id=m.block_id ORDER BY m.id")
    tokens = re.findall(r"\w+", query.lower())
    ranked = []
    figure = re.search(r"(?:figure|table)\s*(\d+\.\d+)",query,re.I)
    standards = reference_mentions(query)
    semantic: dict[str,float] = {}
    pixel_ranks: dict[str,float] = {}
    warnings = []
    if query and not figure and store.config.qdrant_url and configured(store):
        discovered = search(store,ontology,query,manifest,limit=30)
        for index,c in enumerate(discovered['items']):
            for mid in c['metadata'].get('media_occurrence_ids',[]):
                semantic[mid] = max(semantic.get(mid,0),12/(index+1))
    if query and not figure and visual.configured(store) and store.config.qdrant_url:
        _, projections = manifest_chunks(store, manifest)
        profile = visual.spec(visual.selected_config(store)).profile
        matching = [p['id'] for p in projections if json.loads(p['receipts']).get('visuals', {}).get('profile') == profile]
        if len(matching) != len(projections):
            warnings.append('Visual embedding profile changed: rebuild the image index for complete coverage')
        try:
            candidates = visual.VisualProjection(store).search(query, matching)
            source_records = {record['id']: record for doc in docs for record in visual.media_records(store, doc)}
            for index, candidate in enumerate(candidates):
                original = source_records.get(candidate['id'])
                if original and all(candidate.get(field) == original[source_field] for field, source_field in
                    [('asset_id','asset_id'), ('asset_hash','sha256'), ('context_hash','context_hash'), ('document_version_id','document_id')]):
                    pixel_ranks[candidate['id']] = 12/(index+1)
                else:
                    warnings.append('Stale visual vector rejected; source asset/context did not match')
        except Exception:
            warnings.append('Visual embedding search unavailable; OCR, captions and linked text remain available')
    for m in rows:
        if m["document_id"] not in docs or role and m["role"] != role:
            continue
        units = store.all("SELECT i.title FROM units u JOIN unit_blocks ub ON ub.unit_id=u.id LEFT JOIN items i ON i.id=u.item_id WHERE ub.block_id=?", (m["block_id"],))
        text = (m["caption"] + " " + m["ocr"] + " " + " ".join(u["title"] or "" for u in units)).lower()
        score = float(sum(1 for t in tokens if t in text))
        # Exact figure identifiers take priority over general source-family/year matches.
        if figure:
            ident=json.loads(m['identity_json'])
            if not any(f['number']==figure.group(1) for f in ident.get('fragments',[])):
                continue
            if standards and ident.get('references') and not any(all(target.get(k) is None or candidate.get(k)==target.get(k) for k in ['family','part','year']) for target in standards for candidate in ident['references']):
                continue
            score += 50
        score += semantic.get(m['id'],0)
        score += pixel_ranks.get(m['id'],0)
        if not tokens or score:
            ranked.append((score, m["id"]))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    chosen = ranked[offset:offset + limit]
    results = []
    for _, mid in chosen:
        item = media_detail(store, mid)
        item['retrieval_methods'] = ['pixel_semantic'] if mid in pixel_ranks else []
        if mid in semantic:
            item['retrieval_methods'].append('linked_text')
        if not item['retrieval_methods']:
            item['retrieval_methods'] = ['exact_figure' if figure else 'ocr_caption_context' if query else 'source_listing']
        results.append(item)
    return {"items": results, "total": len(ranked), "warnings": sorted(set(warnings)),
        "next_cursor": str(offset + limit) if offset + limit < len(ranked) else None,
        "manifest_id": manifest, "coverage": ("Multimodal image retrieval + OCR/caption/linked text" if pixel_ranks else
            "OCR/caption/catalog context") + "; unreviewed identifications"}


def finding_bundle(store: Store, fid: str):
    f = store.one("SELECT f.*,i.title,d.filename FROM findings f JOIN items i ON i.id=f.item_id JOIN documents d ON d.id=f.document_id WHERE f.id=?", (fid,))
    if not f:
        raise KeyError("Unknown occurrence")
    f["occurrences"] = store.all("SELECT * FROM findings WHERE item_id=? ORDER BY id", (f["item_id"],))
    f["sections"] = store.all("SELECT u.*,p.text,p.block_ids FROM units u JOIN parents p ON p.id=u.parent_id WHERE u.item_id=? AND (u.finding_id=? OR u.finding_id IS NULL)", (f["item_id"], fid))
    for u in f["sections"]:
        u["anchor_ids"] = [r["id"] for bid in json.loads(u["block_ids"]) for r in store.all("SELECT id FROM anchors WHERE block_id=?", (bid,))]
    f["options"] = store.all("SELECT o.*,p.text FROM options o JOIN parents p ON p.id=o.parent_id WHERE o.item_id=?", (f["item_id"],))
    f["work_events"] = store.all("SELECT * FROM work_events WHERE item_id=?", (f["item_id"],))
    f["media"] = store.all("SELECT DISTINCT m.id,m.asset_id,m.role,m.caption,m.identity_json FROM media m JOIN unit_blocks ub ON ub.block_id=m.block_id JOIN units u ON u.id=ub.unit_id WHERE u.item_id=? ORDER BY CASE WHEN m.identity_json LIKE '%2.17%' THEN 0 WHEN m.role='standard_extract' THEN 1 ELSE 2 END,m.id", (f["item_id"],))
    for visual in f["media"]:
        visual["identity"] = json.loads(visual.pop("identity_json"))
        visual["original_url"] = "/api/assets/" + visual["asset_id"] + "/content"
    return f


def enumerate_findings(store: Store, query: str, manifest=None, offset=0, limit=30, document_id=None):
    manifest = manifest or store.active_manifest()
    rows = store.all("SELECT f.*,i.title,d.filename FROM findings f JOIN items i ON i.id=f.item_id JOIN documents d ON d.id=f.document_id JOIN manifest_members mm ON mm.document_id=f.document_id WHERE mm.manifest_id=? ORDER BY f.id", (manifest,))
    chunk_ids,_ = manifest_chunks(store,manifest)
    metadata = store.all("SELECT metadata FROM chunk_revisions WHERE id IN ("+ ",".join("?" for _ in chunk_ids)+")",chunk_ids) if chunk_ids else []
    allowed = {fid for row in metadata for fid in json.loads(row['metadata']).get('occurrence_ids',[])}
    rows = [r for r in rows if r['id'] in allowed]
    manifest_record=store.require('SELECT capabilities FROM manifests WHERE id=?',(manifest,))
    review_ids=json.loads(manifest_record['capabilities']).get('identity_reviews',[])
    equivalents=store.all("SELECT * FROM finding_equivalences WHERE id IN ("+','.join('?' for _ in review_ids)+")",review_ids) if review_ids else []
    for mapping in equivalents:
        if not document_id and mapping['canonical_finding_id'] in allowed and mapping['alias_finding_id'] in allowed:
            rows=[r for r in rows if r['id']!=mapping['alias_finding_id']]
    tokens = re.findall(r"\w+", query.lower())
    filtered = [r for r in rows if (not document_id or r["document_id"] == document_id) and all(t in (r["title"] + " " + r["identifier"] + " " + r["location"]).lower() for t in tokens)]
    pending = store.require("SELECT COUNT(*) n FROM documents WHERE archived=0 AND status<>'ready'")["n"]
    return {"items": filtered[offset:offset + limit], "total": len(filtered),
        "next_cursor": str(offset + limit) if offset + limit < len(filtered) else None,
        "manifest_id": manifest, "coverage": "limited; candidate occurrences and partial/unprocessed sources" if pending else "published structural occurrences", "unprocessed_or_partial": pending}


def canonical_graph(store: Store, finding_id: str, limit=100):
    f = finding_bundle(store, finding_id)
    subjects = [finding_id, f["item_id"]]
    assertions = store.all("SELECT * FROM assertions WHERE subject_id IN (?,?)", subjects)
    nodes = [{"id": finding_id, "label": f["identifier"], "kind": "Finding"}, {"id": f["item_id"], "label": f["title"], "kind": "DefectItem"}]
    edges = []
    for a in assertions:
        supports = store.all("SELECT anchor_id FROM assertion_support WHERE assertion_id=?", (a["id"],))
        nodes.append({"id": a["id"], "label": a["predicate"].replace("_", " "), "kind": "Assertion", "assertion": {**a, "anchor_ids": [s["anchor_id"] for s in supports]}})
        edges.append({"id": identity("edge", a["subject_id"], a["id"]), "source": a["subject_id"], "target": a["id"], "label": a["scope"]})
        if a["object_id"]:
            entity = store.require("SELECT * FROM entities WHERE id=?", (a["object_id"],))
            nodes.append({"id": entity["id"], "label": entity["label"], "kind": entity["kind"]})
            edges.append({"id": identity("edge", a["id"], entity["id"]), "source": a["id"], "target": entity["id"], "label": "qualified object"})
    unique = {n["id"]: n for n in nodes}
    selected = list(unique)[:limit]
    return {"nodes": [unique[x] for x in selected], "edges": [e for e in edges if e["source"] in selected and e["target"] in selected][:200],
        "truncated": len(unique) > limit, "coverage": "Canonical provenance preview; Neo4j traversal requires available projection service"}
