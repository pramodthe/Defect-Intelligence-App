import json
from app.contracts import ChunkMetadata
from app.projections import stage
from app.store import Store, digest, identity


def republish_correction(store: Store, ontology, event: dict):
    payload = json.loads(event["payload"])
    doc_id = payload["document_id"]
    successor_id = payload.get("successor_id")
    if successor_id:
        successor = store.require("SELECT * FROM assertions WHERE id=?", (successor_id,))
        predecessor = successor["predecessor_id"]
        chunks = store.all("SELECT c.* FROM chunk_revisions c WHERE document_id=? AND rowid IN (SELECT MAX(rowid) FROM chunk_revisions GROUP BY chunk_id)", (doc_id,))
        for c in chunks:
            meta = json.loads(c["metadata"])
            if predecessor not in meta["assertion_ids"]:
                continue
            rid = identity("chunkrev", c["id"], event["id"], successor_id)
            meta["chunk_revision_id"] = rid
            meta["annotation_revision_id"] = identity("annotation", meta["semantic_revision_id"], successor_id)
            meta["assertion_ids"] = [successor_id if a == predecessor else a for a in meta["assertion_ids"]]
            meta["extraction_review_state"] = "reviewed"
            meta = ChunkMetadata.model_validate(meta).model_dump(mode="json")
            new = {**c, "id": rid, "metadata": meta, "metadata_hash": digest(meta)}
            with store.connect() as con:
                store.insert("chunk_revisions", new, con)
                for s in store.all("SELECT * FROM chunk_segments WHERE revision_id=?", (c["id"],)):
                    store.insert("chunk_segments", {**s, "revision_id": rid}, con)
                for link in store.all("SELECT * FROM chunk_assertions WHERE revision_id=?", (c["id"],)):
                    store.insert("chunk_assertions", {**link, "revision_id": rid, "assertion_id": successor_id if link["assertion_id"] == predecessor else link["assertion_id"]}, con)
                for link in store.all("SELECT * FROM chunk_links WHERE revision_id=?", (c["id"],)):
                    store.insert("chunk_links", {**link, "revision_id": rid}, con)
    result = stage(store, doc_id, ontology)
    manifest = store.activate(result["projection_id"], {"profile": result["profile"], "receipts": result["receipts"]})
    store.execute("UPDATE outbox SET state='complete' WHERE id=?", (event["id"],))
    return {"manifest_id": manifest}
