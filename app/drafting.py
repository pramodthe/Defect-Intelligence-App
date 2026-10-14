"""Run-scoped, attributed drafting facts and exact requirement retrieval.

No declaration activates a regulatory rule or upgrades a historical report.
"""
import json
import re
from typing import Any

from app.applicability import assess
from app.retrieval import manifest_chunks, source
from app.store import canonical, identity

QUESTIONS: list[dict[str, Any]] = [
    {"key": "jurisdiction", "label": "Which state or territory is the building in?", "options": ["NSW", "VIC", "QLD", "ACT", "SA", "WA", "TAS", "NT", "Unknown"]},
    {"key": "building_class", "label": "What is the building class?", "hint": "For example, Class 1a or Class 2. Use Unknown if it has not been established."},
    {"key": "code_edition", "label": "Which BCA/NCC edition applies, or what is the approval/construction date?", "hint": "Record what you know. A construction year alone does not establish the applicable edition."},
    {"key": "assessment_scope", "label": "Are you assessing existing work or designing a proposed repair?", "options": ["Existing work", "Proposed repair", "Unknown"]},
    {"key": "observations", "label": "Where is the water escaping, and what has been observed?", "hint": "For example, at the bathroom doorway into the hallway. Describe the evidence; use Unknown if inspection is pending."},
    {"key": "compliance_pathway", "label": "Is the relevant work Deemed-to-Satisfy or a Performance Solution?", "options": ["Deemed-to-Satisfy", "Performance Solution", "Unknown"]},
]
UNKNOWN = {"unknown", "not known", "unsure", "not sure", "n/a", "pending"}


def drafting_record(store, run_id):
    row = store.require("SELECT * FROM run_drafting WHERE run_id=?", (run_id,))
    return {**row, "facts": json.loads(row["facts"]), 'conversation': json.loads(row['conversation']),
            'clarification': json.loads(row['clarification']) if row['clarification'] else None}


def validate_chat_response(record, response):
    if response.message.strip():
        return
    questions = (record.get('clarification') or {}).get('questions', [])
    allowed = {q['key'] for q in questions}
    if not response.facts or set(response.facts) != allowed or any(not v.strip() or len(v) > 2000 for v in response.facts.values()):
        raise ValueError('Reply to the assistant, or answer its displayed questions')


def context_values(facts):
    return {k: [v] for k, v in facts.items() if str(v.get("value", "")).lower().strip() not in UNKNOWN}


def drafting_decision(store, run_id):
    run = store.require("SELECT * FROM runs WHERE id=?", (run_id,))
    record = drafting_record(store, run_id)
    ctx = {"id": identity("draft_context", run_id, record["version"], record["facts"]),
           "facts": canonical(context_values(record["facts"]))}
    mode = "remedial" if record["facts"].get("assessment_scope", {}).get("value") == "Proposed repair" else "current"
    decision = assess(store, ctx, mode, rule_ids=json.loads(run["rule_pack_ids"]))
    store.execute("UPDATE run_drafting SET decision_id=? WHERE run_id=?", (decision["id"], run_id))
    return decision


def applicable_requirements(store, run_id, manifest):
    row = store.one("SELECT d.payload FROM run_drafting r JOIN decisions d ON d.id=r.decision_id WHERE r.run_id=?", (run_id,))
    decision = json.loads(row["payload"]) if row else None
    result: dict[str, Any] = {"items": [], "decision": decision, "warnings": [], "coverage": "unresolved"}
    if not decision or decision["disposition"] != "supported":
        result["warnings"] = ["Applicable original requirements could not be verified: reviewed edition/classification rules, original clauses or project facts are missing. Report-cited provisions remain historical evidence."]
        return result
    _, projections = manifest_chunks(store, manifest)
    docs = {p["document_id"] for p in projections}
    for fid in decision["selected_fragment_ids"]:
        fragment = store.one("SELECT f.*,e.document_id,e.label,e.synthetic FROM reference_fragments f JOIN reference_editions e ON e.id=f.edition_id WHERE f.id=?", (fid,))
        if not fragment or fragment["synthetic"] or fragment["document_id"] not in docs or fragment["state"] != "original_context_reviewed":
            result["warnings"].append("An applicable clause is missing from the pinned original-source library")
            continue
        for aid in json.loads(fragment["anchor_ids"]):
            original = source(store, aid)
            if original["document_id"] != fragment["document_id"] or original["content_kind"] != "native_text":
                result["warnings"].append("A requirement lacks exact native original-source text")
                continue
            result["items"].append({"id": identity("evidence", fid, aid), "document_id": fragment["document_id"],
                "header": fragment["label"] + " " + fragment["identifier"], "text": original["quote"],
                "text_kind": "native_text", "anchor_ids": [aid], "segments": [],
                "retrieval_methods": ["exact_governing_fragment"], "manifest_id": manifest,
                "metadata": {"source_role": "original_reference", "section_purpose": "reference_fragment",
                    "content_kind": "native_text", "reference_fragment_id": fid, "edition_id": fragment["edition_id"]}})
    result["coverage"] = "supported" if result["items"] and not result["warnings"] else "incomplete"
    return result


def section_chunks(store, manifest, item_ids):
    ids, _ = manifest_chunks(store, manifest)
    rows = store.all("SELECT * FROM chunk_revisions WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids) if ids else []
    selected = [r for r in rows if json.loads(r["metadata"]).get("defect_item_id") in item_ids]
    items = []
    for row in selected:
        meta = json.loads(row["metadata"])
        if meta["source_role"] != "company_report" or meta["content_kind"] != "native_text":
            continue
        segments = store.all("SELECT s.*,a.id anchor_id FROM chunk_segments s JOIN anchors a ON a.block_id=s.block_id WHERE s.revision_id=? ORDER BY s.sequence", (row["id"],))
        items.append({"id": row["id"], "document_id": row["document_id"], "header": row["header"], "text": row["raw_body"],
            "text_kind": meta["content_kind"], "metadata": meta, "anchor_ids": sorted({s["anchor_id"] for s in segments}),
            "segments": segments, "retrieval_methods": ["original_report_section"], "manifest_id": manifest})
    return {"items": items, "warnings": ["Retrieved TCA report material is historical source evidence; approval for reuse has not been established."],
            "coverage": "Complete published native text for selected report items; original file remains authoritative"}


def scoped_media(bundle):
    """Keep source images linked to retrieved report items; never infer pixel content."""
    allowed = {m for e in bundle.get("items", []) for m in e.get("metadata", {}).get("media_occurrence_ids", [])}
    return [m for m in bundle.get("media", []) if m["id"] in allowed]


def is_unqualified_compliance_claim(text):
    return bool(re.search(r"\b(breach(?:es)?|violat(?:es|ion)|non[- ]compliant|fails? to comply)\b", text, re.I))
