import json
import re
from app.contracts import EditionReview, FragmentReview, ReferenceReview
from app.store import Store, digest, identity


def original_anchors(store: Store, anchors: list[str], document_id: str):
    for aid in anchors:
        a = store.require("SELECT a.document_id,d.role FROM anchors a JOIN documents d ON d.id=a.document_id WHERE a.id=?", (aid,))
        if a["document_id"] != document_id or a["role"] != "original_reference":
            raise ValueError("Original reference anchors with correct ownership required")


def review_edition(store: Store, request: EditionReview):
    original_anchors(store, request.anchor_ids, request.document_id)
    if request.family.upper().startswith("AS") and not re.fullmatch(r"AS\s+\d{4}", request.family.upper()):
        raise ValueError("AS family and numeric part must be supplied separately")
    if request.family.upper().startswith("AS") and request.volume:
        raise ValueError("AS part and code volume are distinct identity fields")
    if not request.family.upper().startswith("AS") and request.part:
        raise ValueError("Use a code volume field, not an AS part")
    version = [request.family.upper(), request.part, request.year, request.volume, request.amendments]
    eid = identity("edition", version)
    label = request.family + ("." + request.part if request.part else "") + "-" + request.year + (" Volume " + request.volume if request.volume else "")
    store.insert("reference_editions", {"id": eid, "document_id": request.document_id, "label": label,
        "family": request.family.upper(), "part": request.part, "year": request.year, "volume": request.volume,
        "amendments": request.amendments, "state": "original_identity_reviewed", "reviewer": request.reviewer,
        "anchor_ids": request.anchor_ids, "identity_hash": digest(version), "synthetic": int(request.synthetic)})
    # Demands extend source coverage; reported citations themselves remain immutable.
    store.execute("UPDATE demands SET state='original_available_identity_reviewed_fragments_pending' WHERE label=?", (label,))
    store.insert("outbox", {"id": identity("outbox", eid), "kind": "reference_reprojection", "payload": {"document_id":request.document_id}, "state":"pending"})
    return {"id": eid, "label": label, "state": "original_identity_reviewed", "applicability": "unresolved"}


def review_fragment(store: Store, request: FragmentReview):
    edition = store.require("SELECT * FROM reference_editions WHERE id=?", (request.edition_id,))
    original_anchors(store, request.anchor_ids, edition["document_id"])
    for dependency in request.dependency_ids:
        if not store.one("SELECT id FROM reference_fragments WHERE id=? AND edition_id=?", (dependency, request.edition_id)):
            raise ValueError("Fragment dependencies must resolve within the exact edition")
    fid = identity("fragment", request.edition_id, request.kind, request.identifier)
    store.insert("reference_fragments", {"id": fid, "edition_id": request.edition_id, "kind": request.kind,
        "identifier": request.identifier, "anchor_ids": request.anchor_ids, "dependencies": request.dependency_ids,
        "state": "original_context_reviewed"})
    store.insert("outbox", {"id": identity("outbox", fid), "kind": "reference_reprojection", "payload": {"document_id":edition["document_id"]}, "state":"pending"})
    return {"id": fid, "state": "original_context_reviewed"}


def review_relationship(store: Store, request: ReferenceReview):
    fragment = store.require("SELECT f.*,e.document_id FROM reference_fragments f JOIN reference_editions e ON e.id=f.edition_id WHERE f.id=?", (request.from_fragment_id,))
    store.require("SELECT * FROM reference_editions WHERE id=?", (request.to_edition_id,))
    original_anchors(store, request.anchor_ids, fragment["document_id"])
    from app.applicability import predicate
    predicate(request.predicates, {})  # Validate only the permitted typed predicate language.
    rid = identity("referencechain", request.model_dump())
    store.insert("reference_relationships", {"id": rid, "from_fragment_id": request.from_fragment_id,
        "to_edition_id": request.to_edition_id, "basis": request.basis, "scope": request.scope,
        "predicates": request.predicates, "anchor_ids": request.anchor_ids, "reviewer": request.reviewer,
        "state": "reviewed", "version": 1})
    store.insert("outbox", {"id": identity("outbox", rid), "kind": "reference_reprojection", "payload": {"document_id":fragment["document_id"]}, "state":"pending"})
    return {"id": rid, "state": "reviewed", "applicability": "requires scoped context evaluation"}


def reference_chain(store: Store, fragment_ids: list[str], facts: dict, allow_synthetic=False):
    from app.applicability import predicate
    results, missing = [], []
    queue = list(fragment_ids)
    visited: set[str] = set()
    while queue and len(visited) < 50:
        fid = queue.pop(0)
        if fid in visited:
            continue
        visited.add(fid)
        fragment = store.one("SELECT f.*,e.synthetic FROM reference_fragments f JOIN reference_editions e ON e.id=f.edition_id WHERE f.id=?", (fid,))
        if not fragment or fragment["synthetic"] and not allow_synthetic:
            missing.append("Missing/non-production original fragment: " + fid)
            continue
        for dep in json.loads(fragment["dependencies"]):
            queue.append(dep)
        relationships = store.all("SELECT r.*,e.synthetic,e.label,e.part,e.year,e.amendments FROM reference_relationships r JOIN reference_editions e ON e.id=r.to_edition_id WHERE r.from_fragment_id=? AND r.state='reviewed'", (fid,))
        for r in relationships:
            condition = predicate(json.loads(r["predicates"]), facts)
            if condition is None:
                missing.append("Unknown condition in reference relationship " + r["id"])
            elif condition is True and (allow_synthetic or not r["synthetic"]):
                results.append({**r, "anchor_ids": json.loads(r["anchor_ids"]), "amendments": json.loads(r["amendments"])})
                queue += [f["id"] for f in store.all("SELECT id FROM reference_fragments WHERE edition_id=?", (r["to_edition_id"],))]
    if queue:
        missing.append("Reference traversal budget reached")
    return {"relationships": results, "missing": missing, "fragment_ids": sorted(visited)}
