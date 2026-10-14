"""Compact model context; the canonical retrieved evidence remains unchanged locally."""
import re
from dataclasses import dataclass

from app.store import canonical, digest

PACK_VERSION = "research-evidence/1"
MAX_CONTEXT_CHARS = 96_000
METADATA_FIELDS = ("source_role", "authority_role", "content_kind", "section_purpose",
                   "defect_item_id", "occurrence_ids", "option_id", "reference_fragment_id",
                   "identified_reference", "extraction_review_state", "warnings", "edition_id")


def compact_metadata(metadata):
    return {key: metadata[key] for key in METADATA_FIELDS if metadata.get(key)}


@dataclass
class EvidencePack:
    payload: dict
    citations: dict[str, str]
    receipt: dict
    gaps: list[str]

    def canonical_claims(self, claims):
        # Unknown labels stay unknown so mechanical verification rejects them.
        return [{**claim, "anchor_ids": [self.citations.get(a, a) for a in claim["anchor_ids"]]}
                for claim in claims]

    def model_claims(self, claims):
        labels = {aid: label for label, aid in self.citations.items()}
        return [{**{k: v for k, v in claim.items() if k != 'quote_anchor_id'},
                 "anchor_ids": [labels.get(a, a) for a in claim["anchor_ids"]]} for claim in claims]


def evidence_pack(store, items, question, max_chars=MAX_CONTEXT_CHARS):
    """Select complete chunks and deduplicate exact paragraphs, never slice source text.

    Short citation labels exist only in the request. Returned labels are resolved to
    immutable anchors before checking or saving claims. If the cap excludes chunks,
    the model and saved answer receive an explicit coverage gap.
    """
    terms = set(re.findall(r"[\w]+", question.lower())) - {"the", "from", "what", "this", "with", "and", "all"}
    def relevance(item):
        header = set(re.findall(r"[\w]+", item["header"].lower()))
        body = set(re.findall(r"[\w]+", item["text"].lower()))
        return 4 * len(terms & header) + len(terms & body)

    ranked = sorted(enumerate(items), key=lambda pair: (-relevance(pair[1]), pair[0]))
    # Related reasoning/repair options for the best matching item stay beside its observations.
    primary = ranked[0][1].get("metadata", {}).get("defect_item_id") if ranked else None
    ranked.sort(key=lambda pair: (pair[1].get("metadata", {}).get("defect_item_id") != primary,
                                  -relevance(pair[1]), pair[0]))
    payload: dict = {"evidence": [], "sources": [], "coverage": {}}
    citations: dict[str, str] = {}
    labels: dict[str, str] = {}
    anchor_ids = sorted({aid for item in items for aid in item['anchor_ids']} |
                        {s['anchor_id'] for item in items for s in item.get('segments', []) if s.get('anchor_id')})
    # Fetch only exact text in one read; source() also hydrates UI/media/table data.
    rows = store.all("SELECT a.id,a.start_cp,a.end_cp,b.text FROM anchors a JOIN blocks b ON b.id=a.block_id "
                     "WHERE a.id IN (" + ','.join('?' for _ in anchor_ids) + ")", anchor_ids) if anchor_ids else []
    cache = {r['id']: {"text": r['text'], "quote": r['text'][r['start_cp']:r['end_cp']]} for r in rows}
    skipped = 0
    for _, item in ranked:
        # Segment order is source order; anchor_ids alone are sorted by hash.
        order = list(dict.fromkeys([s["anchor_id"] for s in item.get("segments", []) if s.get("anchor_id")]
                                  + item["anchor_ids"]))
        additions = []
        candidate_labels = dict(labels)
        for aid in order:
            if aid in candidate_labels:
                continue
            label = "S" + str(len(candidate_labels) + 1)
            candidate_labels[aid] = label
            original = cache[aid]
            passage = {"id": label, "quote": original["quote"]}
            # A partial anchor retains its complete paragraph as qualification context.
            if original["text"] != original["quote"]:
                passage["block_context"] = original["text"]
            additions.append(passage)
        record = {"header": item["header"], "metadata": compact_metadata(item["metadata"]),
                  "anchor_ids": [candidate_labels[aid] for aid in order]}
        candidate = {"evidence": [*payload["evidence"], record],
                     "sources": [*payload["sources"], *additions]}
        # Leave space for the coverage summary; keep each chunk and paragraph complete.
        if len(canonical(candidate)) + 1000 > max_chars:
            skipped += 1
            continue
        payload.update(candidate)
        labels = candidate_labels
    citations = {label: aid for aid, label in labels.items()}
    gaps = [f"Draft context contains {len(payload['evidence'])} of {len(items)} retrieved passages; "
            "other passages remain saved. This answer is not exhaustive."] if skipped else []
    payload["coverage"] = {"retrieved_passages": len(items), "included_passages": len(payload["evidence"]),
                           "omitted_passages": skipped, "gaps": gaps}
    receipt = {"evidence_format": PACK_VERSION, "context_chars": len(canonical(payload)),
               "context_hash": digest(payload), **payload["coverage"], "source_count": len(citations)}
    return EvidencePack(payload, citations, receipt, gaps)
