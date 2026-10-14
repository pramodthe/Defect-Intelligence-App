import json
from app.contracts import ChunkMetadata, Segment
from app.extraction import add_assertion, anchor_for
from app.store import Store, digest, identity


class TokenCounter:
    def __init__(self, path: str = ""):
        self.tokenizer = None
        self.profile = "unicode-conservative/1 (BGE unavailable)"
        if path:
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, use_fast=True)
            self.profile = "bge-tokenizer:" + digest(self.tokenizer.backend_tokenizer.to_str())[:20]
            # Counting an oversized atom is permitted; encode() for embeddings still enforces <=480.
            self.tokenizer.model_max_length = 1_000_000_000

    def count(self, text: str) -> int:
        if self.tokenizer:
            return len(self.tokenizer.encode(text, add_special_tokens=True, truncation=False))
        return len(text) + 2

    def split(self, text: str, header: str) -> list[tuple[int, int]]:
        # Binary source-offset packing preserves every code point; no tokenizer truncation.
        result = []
        start = 0
        while start < len(text):
            lo, hi = start + 1, len(text)
            best = start
            while lo <= hi:
                mid = (lo + hi) // 2
                if self.count(header + "\n" + text[start:mid]) <= 420:
                    best, lo = mid, mid + 1
                else:
                    hi = mid - 1
            if best == start:
                raise ValueError("Retrieval header leaves no source-token allowance")
            if best < len(text):
                # Prefer a sentence/word boundary but retain the original source offsets.
                window = text[start:best]
                boundary = max(window.rfind(". "), window.rfind("\n"), window.rfind(" "))
                if boundary > len(window) * .6:
                    best = start + boundary + 1
            result.append((start, best))
            start = best
        return result


def build_chunks(store: Store, document_id: str, catalog_version: str) -> dict:
    counter = TokenCounter(store.config.tokenizer_path)
    doc = store.require("SELECT * FROM documents WHERE id=?", (document_id,))
    units = store.all("SELECT u.*,p.dependencies FROM units u JOIN parents p ON p.id=u.parent_id WHERE u.document_id=? AND u.semantic_revision=?", (document_id,doc['active_semantic_revision']))
    chunk_ids = []
    covered = 0
    for u in units:
        item = store.require("SELECT title FROM items WHERE id=?", (u["item_id"],)) if u["item_id"] else None
        header = ((item["title"] if item else doc["filename"]) + " | " + u["purpose"])[:140]
        while counter.count(header) > 90:
            header = header[:-10]
        blocks = store.all("SELECT b.* FROM unit_blocks ub JOIN blocks b ON b.id=ub.block_id WHERE ub.unit_id=? ORDER BY ub.sequence", (u["id"],))
        chunks = []
        current_segments: list[Segment] = []
        current_body = ""
        content_kind = "native_text"

        def flush():
            nonlocal current_segments, current_body
            if current_segments:
                chunks.append((list(current_segments), current_body, content_kind))
            current_segments, current_body = [], ""

        for b in blocks:
            text = b["text"]
            if not text.strip():
                continue
            if content_kind and content_kind != b["content_kind"]:
                flush()
            content_kind = b["content_kind"]
            for start, end in counter.split(text, header):
                body = text[start:end]
                candidate = current_body + ("\n" if current_body else "") + body
                if current_body and counter.count(header + "\n" + candidate) > 420:
                    flush()
                current_body += ("\n" if current_body else "") + body
                current_segments.append(Segment(block_id=b["id"], start_cp=start, end_cp=end))
                covered += end - start
                if end < len(text):
                    flush()
        flush()
        for segments, body, kind in chunks:
            segs = [s.model_dump() for s in segments]
            source_hash = digest([document_id, u["structure_id"], u["semantic_revision"], u["id"], kind, segs, counter.profile])
            cid = identity("chunk", source_hash)
            retrieval = header + "\n" + body
            count = counter.count(retrieval)
            if count > 480:
                raise ValueError("Token limit exceeded; no input may be truncated")
            media_ids = []
            concepts = []
            assertions: list[str] = []
            references: list[str] = []
            for s in segments:
                b = store.require("SELECT * FROM blocks WHERE id=?", (s.block_id,))
                if b["document_id"] != document_id or not 0 <= s.start_cp < s.end_cp <= len(b["text"]):
                    raise ValueError("Invalid exact source segment")
                p = json.loads(b["payload"])
                if p.get("media_occurrence_id"):
                    media_ids.append(p["media_occurrence_id"])
                mentions = store.all("SELECT * FROM mentions WHERE block_id=? AND start_cp<? AND end_cp>?", (s.block_id, s.end_cp, s.start_cp))
                for mention in mentions:
                    if mention["concept_id"]:
                        concepts.append(mention["concept_id"])
                anchor = anchor_for(store, s.block_id)
                assertions.extend(r["assertion_id"] for r in store.all("SELECT assertion_id FROM assertion_support WHERE anchor_id=?", (anchor,)))
                references.extend(r["id"] for r in store.all("SELECT id FROM references_catalog WHERE anchor_id=?", (anchor,)))
            revision = identity("chunkrev", cid, digest(retrieval), catalog_version, sorted(set(assertions)), sorted(set(references)))
            identified = {}
            if media_ids:
                identified = {mid: json.loads(store.require("SELECT identity_json FROM media WHERE id=?",(mid,))["identity_json"]) for mid in sorted(set(media_ids))}
            metadata = ChunkMetadata(chunk_id=cid, chunk_revision_id=revision, document_version_id=document_id,
                structure_revision_id=u["structure_id"], semantic_revision_id=u["semantic_revision"],
                logical_unit_id=u["id"], parent_context_id=u["parent_id"], source_role=doc["role"],
                authority_role="report_author_statement" if doc["role"] == "company_report" else "original_source_candidate",
                content_kind=kind, section_path=[item["title"] if item else "", u["purpose"]], section_purpose=u["purpose"],
                defect_item_id=u["item_id"], occurrence_ids=[u["finding_id"]] if u["finding_id"] else [], option_id=u["option_id"],
                media_occurrence_ids=sorted(set(media_ids)), concept_ids=sorted(set(concepts)), assertion_ids=sorted(set(assertions)),
                cited_reference_ids=sorted(set(references)), source_segments=segments,
                identified_reference=identified,
                dependency_ids=json.loads(u["dependencies"]), token_count=count, tokenizer_profile=counter.profile,
                warnings=["Partial deterministic domain extraction; model enrichment unavailable"])
            meta = metadata.model_dump(mode="json")
            revision = identity("chunkrev",cid,digest(retrieval),{k:v for k,v in meta.items() if k!='chunk_revision_id'})
            meta['chunk_revision_id'] = revision
            with store.connect() as con:
                store.insert("chunks", {"id": cid, "unit_id": u["id"], "content_kind": kind,
                    "profile": "structure-bge/1", "source_identity_hash": source_hash}, con)
                store.insert("chunk_revisions", {"id": revision, "chunk_id": cid, "document_id": document_id,
                    "parent_id": u["parent_id"], "raw_body": body, "header": header, "retrieval_text": retrieval,
                    "text_hash": digest(retrieval), "metadata": meta, "metadata_hash": digest(meta), "token_count": count}, con)
                for index, s in enumerate(segments):
                    store.insert("chunk_segments", {"revision_id": revision, "sequence": index, **s.model_dump()}, con)
                for assertion in set(assertions):
                    store.insert("chunk_assertions", {"revision_id": revision, "assertion_id": assertion, "role": "direct"}, con)
            for concept in set(concepts):
                mapping = add_assertion(store, document_id, u["id"], "mentions_concept", concept,
                    [anchor_for(store, s.block_id) for s in segments], "source_supported_mapping", "unit:" + u["id"])
                store.insert("chunk_links", {"revision_id": revision, "concept_id": concept, "assertion_id": mapping,
                    "role": "direct", "catalog_version": catalog_version})
            chunk_ids.append(revision)
    return {"chunk_revision_ids": chunk_ids, "source_codepoints_covered": covered, "tokenizer_profile": counter.profile}
