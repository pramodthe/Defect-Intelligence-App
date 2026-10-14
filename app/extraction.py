import json
import re

from app.ontology import Ontology
from app.store import Store, canonical, digest, identity

DS = re.compile(r"\bDS\s*[-–—:]?\s*(\d+)", re.I)
AS = re.compile(r"\bAS\s*(\d{4})(?:\s*\.\s*(\d+))?(?:\s*[-–—:\s]\s*((?:19|20)\d{2}))?", re.I)
CODE = re.compile(r"\b(NCC|BCA)(?:\s*(?:edition|version))?\s*[-–—:]?\s*((?:19|20)\d{2})", re.I)
FIGURE = re.compile(r"\b(FIGURE|TABLE|CLAUSE)\s+(\d+(?:\.\d+)+)", re.I)
ROLES = {"sample findings": "observation", "occurrence": "extent", "status": "status", "result": "result",
         "reasoning": "reasoning", "responsibility": "responsibility", "remediation": "remediation",
         "defect": "observation"}


def anchor_for(store: Store, block_id: str) -> str:
    return store.require("SELECT id FROM anchors WHERE block_id=? ORDER BY start_cp LIMIT 1", (block_id,))["id"]


def add_review(store: Store, document_id: str, kind: str, message: str, anchors: list[str], assertion_id=None):
    rid = identity("review", document_id, kind, message, anchors)
    store.insert("reviews", {"id": rid, "document_id": document_id, "assertion_id": assertion_id,
        "kind": kind, "message": message, "anchor_ids": anchors, "state": "needs_review", "version": 1, "payload": {}})


def add_assertion(store: Store, document_id: str, subject: str, predicate: str, value: str,
                  anchors: list[str], kind="author_opinion", scope="item", object_id=None):
    aid = identity("assertion", document_id, subject, predicate, value, anchors, scope)
    store.insert("assertions", {"id": aid, "document_id": document_id, "subject_id": subject,
        "predicate": predicate, "object_id": object_id, "value": value, "kind": kind, "scope": scope,
        "state": "extracted", "version": 1, "payload": {"method": "structural_source_mapping/1"}})
    for anchor in anchors:
        a = store.one("SELECT document_id FROM anchors WHERE id=?", (anchor,))
        if not a or a["document_id"] != document_id:
            raise ValueError("Foreign/invalid assertion support")
        store.insert("assertion_support", {"assertion_id": aid, "anchor_id": anchor})
    return aid


def reference_mentions(text: str) -> list[dict]:
    candidates = []
    for m in AS.finditer(text):
        family, part, year = m.groups()
        label = "AS " + family + ("." + part if part else "") + ("-" + year if year else "")
        candidates.append({"label": label, "start": m.start(), "end": m.end(),
                           "family": "AS " + family, "part": part, "year": year, "amendments": None})
    for m in CODE.finditer(text):
        volume = re.search(r"Volume\s+(One|Two|Three|1|2|3|I{1,3})", text[m.end():m.end() + 100], re.I)
        label = m.group(1).upper() + " " + m.group(2) + (" Volume " + volume.group(1) if volume else "")
        candidates.append({"label": label, "start": m.start(), "end": m.end(), "family": m.group(1).upper(),
                           "part": None, "year": m.group(2), "volume": volume.group(1) if volume else None, "amendments": None})
    return candidates


def materialize_visual_blocks(store: Store, document_id: str):
    visuals = store.all("SELECT v.*,m.block_id,m.asset_id,m.identity_json,b.structure_id,b.locator,b.sequence FROM visuals v JOIN media m ON m.id=v.media_id JOIN blocks b ON b.id=m.block_id WHERE m.document_id=?", (document_id,))
    for v in visuals:
        if not v["text"]:
            continue
        bid = identity("block", v["id"], "ocr")
        store.insert("blocks", {"id": bid, "document_id": document_id, "structure_id": v["structure_id"],
            "parent_id": v["block_id"], "kind": "ocr_region", "sequence": 1_000_000 + v["sequence"],
            "text": v["text"], "content_kind": "ocr_text", "locator": json.loads(v["locator"]),
            "payload": {"media_occurrence_id": v["media_id"], "visual_revision_id": v["id"],
                        "regions": json.loads(v["regions"]), "warnings": json.loads(v["warnings"])}})
        store.insert("anchors", {"id": identity("anchor", bid, 0, len(v["text"])), "block_id": bid,
            "document_id": document_id, "start_cp": 0, "end_cp": len(v["text"]), "quote_hash": digest(v["text"])})
        mentions = reference_mentions(v["text"])
        fragments = [{"kind": m.group(1).lower(), "number": m.group(2)} for m in FIGURE.finditer(v["text"])]
        page = re.search(r"^\s*(\d{1,3})\s*$", v["text"], re.M)
        identification = {"references": mentions, "fragments": fragments,
            "source_printed_page": page.group(1) if page else None,
            "state": "visible_ocr_candidate" if mentions else "unknown", "basis": v["id"],
            "original_verification": "embedded_extract_only", "applicability": "unresolved"}
        store.execute("UPDATE media SET identity_json=? WHERE id=?", (canonical(identification), v["media_id"]))


def build_units(store: Store, document_id: str, ontology: Ontology) -> dict:
    materialize_visual_blocks(store, document_id)
    blocks = store.all("SELECT * FROM blocks WHERE document_id=? ORDER BY sequence", (document_id,))
    doc = store.require("SELECT * FROM documents WHERE id=?", (document_id,))
    structure_id = store.require("SELECT id FROM structures WHERE document_id=? ORDER BY rowid DESC LIMIT 1", (document_id,))["id"]
    sem = identity("semantic", structure_id, "structural-domain/1", ontology.version)
    items = []
    current_item = None
    purpose = "context"
    occurrence = None
    option_id = None
    current_group: list[dict] = []
    groups = []
    block_to_item = {}

    def flush():
        nonlocal current_group
        if current_group:
            groups.append((current_item, purpose, occurrence, option_id, current_group))
            current_group = []

    def create_item(b, title):
        iid = identity("item", document_id, b["id"])
        store.insert("items", {"id": iid, "document_id": document_id, "title": title, "heading_anchor_id": anchor_for(store, b["id"])})
        store.insert("entities", {"id": iid, "document_id": document_id, "kind": "DefectItem", "label": title, "payload": {}})
        items.append(iid)
        return iid

    for b in blocks:
        if b["content_kind"] == "ocr_text":
            continue
        p = json.loads(b["payload"])
        if p.get('has_text_children'):
            continue
        text = b["text"].strip()
        level = p.get("heading_level")
        role_heading=any(text.lower().rstrip(':').startswith(label) for label in ROLES)
        if doc["role"] == "company_report" and b["kind"] == "heading" and (level == 1 or p.get('docling_ref')) and text and not role_heading:
            flush()
            current_item = create_item(b, text)
            purpose, occurrence, option_id = "context", None, None
        elif not current_item and text:
            current_item = create_item(b, "Document context")
        key = re.split(r"[:(–—]", text.lower())[0].strip()
        role = next((value for label, value in ROLES.items() if key == label or key.startswith(label + " ")), None)
        if role and (p.get("style_id") in {"CHeading", "Heading3", "Heading4"} or len(text) < 80):
            flush()
            purpose, occurrence = role, None
            option_id = identity("option", document_id, b["id"]) if role == "remediation" else None
        if purpose == "remediation" and re.match(r"(?:option|alternative)\s*\d", text, re.I):
            flush()
            option_id = identity("option", document_id, b["id"])
        matches = list(DS.finditer(text))
        pdf_candidate=json.loads(b['locator'])['format']=='pdf' and purpose=='context'
        if matches and current_item and (purpose == "observation" or pdf_candidate):
            flush()
            occurrence = identity("finding", document_id, b["id"], matches[0].start())
            identifier = "DS-" + matches[0].group(1)
            location = text[matches[0].end():].strip(" ,:-–—")
            store.insert("findings", {"id": occurrence, "item_id": current_item, "document_id": document_id,
                "identifier": identifier, "location": location, "anchor_id": anchor_for(store, b["id"]), "scope_state": "structural_candidate"})
            if pdf_candidate:
                add_review(store,document_id,'pdf_occurrence_scope','PDF DS/location candidate requires item-scope review',[anchor_for(store,b['id'])])
            store.insert("entities", {"id": occurrence, "document_id": document_id, "kind": "Finding", "label": identifier + " " + location, "payload": {"item_id": current_item}})
            add_assertion(store, document_id, current_item, "has_occurrence", identifier,
                          [anchor_for(store, b["id"])], "recorded_observation", "item", occurrence)
        if current_item:
            block_to_item[b["id"]] = current_item
            current_group.append(b)
        if re.search(r"Attachment\s+[A-Z]", text):
            add_review(store, document_id, "attachment_scope", "Referenced attachment needs supplied-source identity review", [anchor_for(store, b["id"])])
        if re.search(r"repair.*(?:failed|failure)|(?:failed|failure).*repair", text, re.I) and current_item:
            store.insert("work_events", {"id": identity("work", b["id"]), "item_id": current_item,
                "kind": "reported_repair_history", "anchor_id": anchor_for(store, b["id"]),
                "payload": {"text": b["text"], "date": None, "outcome": "reported_failure_candidate"}})
    flush()
    for b in blocks:
        if b["content_kind"] == "ocr_text":
            parent = b["parent_id"]
            iid = block_to_item.get(parent)
            groups.append((iid, "visual_extract", None, None, [b]))
    units = []
    for iid, role, finding, option, group in groups:
        # Native, OCR and serialized table text never share a quotation/chunk unit.
        by_kind: dict[str, list[dict]] = {}
        for b in group:
            by_kind.setdefault(b["content_kind"], []).append(b)
        for content_kind, rows in by_kind.items():
            if not any(b["text"].strip() or b["kind"] == "picture_occurrence" for b in rows):
                continue
            uid = identity("unit", sem, role, iid, finding, option, [b["id"] for b in rows])
            parent_id = identity("parent", uid)
            body = "\n".join(b["text"] for b in rows if b["text"].strip())
            store.insert("parents", {"id": parent_id, "document_id": document_id, "text": body,
                                     "block_ids": [b["id"] for b in rows], "dependencies": []})
            store.insert("units", {"id": uid, "document_id": document_id, "structure_id": structure_id,
                "semantic_revision": sem, "kind": "remediation_option" if option else "occurrence_observation" if finding else role,
                "purpose": role, "item_id": iid, "finding_id": finding, "option_id": option,
                "parent_id": parent_id, "scope_state": "occurrence" if finding else "item_shared" if iid else "unresolved"})
            for index, b in enumerate(rows):
                store.insert("unit_blocks", {"unit_id": uid, "block_id": b["id"], "sequence": index})
            if option and iid:
                store.insert("options", {"id": option, "item_id": iid, "title": next((b["text"] for b in rows if b["text"].strip()), "Remediation option"),
                    "parent_id": parent_id, "alternative_group": iid, "state": "extracted"})
            store.insert("entities", {"id": uid, "document_id": document_id, "kind": "AuthoredReasoning" if role == "reasoning" else "RemediationOption" if option else "Assessment",
                "label": role.replace("_", " "), "payload": {"parent_id": parent_id, "option_id": option}})
            supports = [anchor_for(store, b["id"]) for b in rows if b["text"].strip()]
            if supports and iid:
                pred = {"reasoning": "has_reasoning", "remediation": "has_remediation", "status": "has_status", "result": "has_result",
                        "extent": "has_extent", "responsibility": "has_responsibility"}.get(role, "records")
                add_assertion(store, document_id, finding or iid, pred, role, supports,
                    "recorded_observation" if role == "observation" else "ocr_extraction" if content_kind == "ocr_text" else "author_opinion",
                    "occurrence" if finding else "item_shared", uid)
            units.append(uid)
    collisions = store.all("SELECT identifier,COUNT(*) n FROM findings WHERE document_id=? GROUP BY identifier HAVING COUNT(*)>1", (document_id,))
    for c in collisions:
        rows = store.all("SELECT anchor_id FROM findings WHERE document_id=? AND identifier=?", (document_id, c["identifier"]))
        add_review(store, document_id, "identifier_collision", c["identifier"] + " repeats; confirm occurrence/schedule identity before merging", [r["anchor_id"] for r in rows])
    store.execute("UPDATE documents SET active_semantic_revision=? WHERE id=?",(sem,document_id))
    return {"semantic_revision": sem, "unit_ids": units, "item_ids": items, "scope": "partial_structural_extraction"}


def annotate_domain(store: Store, document_id: str, ontology: Ontology) -> dict:
    blocks = store.all("SELECT * FROM blocks WHERE document_id=? AND text<>''", (document_id,))
    count = 0
    years: dict[str, set[str]] = {}
    for b in blocks:
        text = b["text"]
        anchor = anchor_for(store, b["id"])
        units = store.all("SELECT u.* FROM units u JOIN unit_blocks ub ON ub.unit_id=u.id WHERE ub.block_id=?", (b["id"],))
        if not units:
            continue
        unit = units[0]
        title = store.one("SELECT title FROM items WHERE id=?", (unit["item_id"],)) if unit["item_id"] else None
        for c in ontology.resolve(text, (title["title"] if title else "") + " " + text):
            for start, end in c["spans"]:
                mention_id = identity("mention", b["id"], start, end, c["id"], ontology.version)
                store.insert("mentions", {"id": mention_id, "block_id": b["id"], "start_cp": start, "end_cp": end,
                    "concept_id": c["id"], "entity_id": unit["finding_id"] or unit["item_id"], "method": "governed_alias_span/1",
                    "state": "needs_review" if c["ambiguity"] == "candidate" else "extracted", "catalog_version": ontology.version})
            if c["ambiguity"] == "candidate":
                add_review(store, document_id, "class_family", "Class term is a " + c["family"] + " candidate; no building classification inferred", [anchor])
        for ref in reference_mentions(text):
            rid = identity("reference", document_id, b["id"], ref["start"], ref["label"])
            source_identity = {**ref, "basis": "ocr_visible_candidate" if b["content_kind"] == "ocr_text" else "report_cited",
                               "original_verification": "unverified", "authority_role": "original_reference_candidate" if store.require("SELECT role FROM documents WHERE id=?", (document_id,))["role"] == "original_reference" else "report_reference"}
            store.insert("references_catalog", {"id": rid, "document_id": document_id, "anchor_id": anchor,
                "label": ref["label"], "normalized": re.sub(r"[^a-z0-9]", "", ref["label"].lower()),
                "identity_json": source_identity, "state": "reported_only"})
            store.insert("demands", {"id": identity("demand", rid), "label": ref["label"], "identity_json": source_identity,
                "state": "missing_original_or_reviewed_identity", "origin_reference_id": rid})
            if ref["year"]:
                years.setdefault(ref["family"], set()).add(ref["year"])
            subject = unit["finding_id"] or unit["item_id"]
            if subject:
                add_assertion(store, document_id, subject, "cites", ref["label"], [anchor], "reported_reference", "unit:" + unit["id"])
            count += 1
    for family, cited_years in years.items():
        if len(cited_years) > 1:
            rows = store.all("SELECT anchor_id FROM references_catalog WHERE document_id=? AND label LIKE ?", (document_id, family + "%"))
            add_review(store, document_id, "mixed_citation_years", family + " has multiple cited years; preserve purposes and check original sources", [r["anchor_id"] for r in rows])
    return {"reference_mentions": count, "catalog_version": ontology.version, "domain_enrichment": "partial; model unconfigured unless explicitly enabled"}


def validate_candidates(store: Store, document_id: str, ontology: Ontology, candidates):
    for c in candidates.assertions:
        if c.predicate not in ontology.predicates or c.predicate in {"classified_as", "references"}:
            raise ValueError("Model cannot establish normative/classification relationships")
        for endpoint in [c.subject_id, c.object_id]:
            if endpoint and not store.one("SELECT id FROM entities WHERE id=? AND document_id=?", (endpoint, document_id)):
                raise ValueError("Foreign or nonexistent extraction endpoint")
        if len(c.anchor_ids) != len(c.quotations) or not c.anchor_ids:
            raise ValueError("Exact source quotations required")
        for aid, quote in zip(c.anchor_ids, c.quotations, strict=True):
            row = store.one("SELECT a.*,b.text FROM anchors a JOIN blocks b ON b.id=a.block_id WHERE a.id=? AND a.document_id=?", (aid, document_id))
            if not row or not quote or quote not in row["text"][row["start_cp"]:row["end_cp"]]:
                raise ValueError("Fabricated or foreign source span")
        add_assertion(store, document_id, c.subject_id, c.predicate, c.value, c.anchor_ids, c.kind, c.scope, c.object_id)
    return {"assertion_count": len(candidates.assertions), "warnings": candidates.warnings}
