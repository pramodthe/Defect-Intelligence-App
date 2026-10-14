from app.contracts import Claim
from app.retrieval import manifest_chunks, source
from app.store import Store


def verify_claim(store: Store, claim: Claim, manifest: str, evidence: list[dict], decision=None) -> dict:
    reasons = []
    allowed_anchors = {aid for e in evidence for aid in e.get("anchor_ids", [])}
    _, projections = manifest_chunks(store, manifest)
    allowed_docs = {p["document_id"] for p in projections}
    if not claim.anchor_ids:
        reasons.append("No source support")
    sources = []
    for aid in claim.anchor_ids:
        try:
            s = source(store, aid)
            sources.append(s)
            if s["document_id"] not in allowed_docs or aid not in allowed_anchors:
                reasons.append("Anchor outside pinned evidence/manifest")
        except KeyError:
            reasons.append("Nonexistent source anchor")
    if claim.quote and not any(claim.quote in s["quote"] for s in sources):
        reasons.append("Quoted source text does not match")
    if claim.kind == "governing":
        if not decision or decision["disposition"] != "supported" or claim.decision_id != decision["id"]:
            reasons.append("No supported applicability decision")
        if claim.edition_id not in (decision or {}).get("selected_editions", []):
            reasons.append("Edition not established by reviewed chain")
        if claim.fragment_id not in (decision or {}).get("selected_fragment_ids", []):
            reasons.append("Exact clause/fragment not established")
        fragment=store.one('SELECT * FROM reference_fragments WHERE id=?',(claim.fragment_id,))
        if not fragment or fragment['edition_id']!=claim.edition_id:
            reasons.append('Claim fragment belongs to a different edition')
        elif not set(claim.anchor_ids).intersection(__import__('json').loads(fragment['anchor_ids'])):
            reasons.append('Governing claim lacks its exact fragment source support')
        classification = (decision or {}).get("classification", {}).get("effects", [])
        classes = {effect.get("class_id") for effect in classification}
        if claim.building_class not in classes:
            reasons.append("Building-part classification incompatible or missing")
        if any(s["content_kind"] != "native_text" for s in sources):
            reasons.append("OCR/description cannot alone verify original governing text")
    if claim.kind == "report_excerpt" and any(s["content_kind"] == "ocr_text" for s in sources):
        reasons.append("OCR must retain extraction status")
    # Deterministic fallback accepts only a literal quotation, never generated report paraphrases.
    return {"accepted": not reasons, "reasons": reasons, "claim": claim.model_dump(mode="json")}


def fact_context(store: Store, project_id: str | None, part_id: str | None, mode: str):
    if not project_id:
        return None
    purpose = "proposed_remedial_work" if mode == "remedial" else "original_work_assessment"
    return store.one("SELECT * FROM contexts WHERE project_id=? AND part_id IS ? AND purpose=? ORDER BY version DESC LIMIT 1", (project_id, part_id, purpose))
