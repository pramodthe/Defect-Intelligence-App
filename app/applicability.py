import json
from typing import Any
from app.contracts import Rule
from app.store import Store, identity


def predicate(expr: dict, facts: dict) -> bool | None:
    if "all" in expr:
        results = [predicate(e, facts) for e in expr["all"]]
        return False if False in results else None if None in results else True
    if "any" in expr:
        results = [predicate(e, facts) for e in expr["any"]]
        return True if True in results else None if None in results else False
    if "not" in expr:
        result = predicate(expr["not"], facts)
        return None if result is None else not result
    field, op = expr.get("field"), expr.get("op")
    if op not in {"eq", "in", "lt", "lte", "gt", "gte", "exists"} or not isinstance(field, str):
        raise ValueError("Unsupported typed rule predicate")
    fact = facts.get(field)
    if fact is None:
        return None
    values = fact if isinstance(fact, list) else [fact]
    if len(values) != 1:
        return None
    value = values[0].get("value") if isinstance(values[0], dict) else values[0]
    if value is None:
        return None
    target = expr.get("value")
    if op == "exists":
        return True
    if op == "eq":
        return value == target
    if op == "in":
        if not isinstance(target, list):
            raise ValueError("Membership predicate requires a typed list")
        return value in target
    try:
        return {"lt": lambda: value < target, "lte": lambda: value <= target,
                "gt": lambda: value > target, "gte": lambda: value >= target}[op]()
    except TypeError:
        return None


def validate_activation(rule: Rule, store: Store, allow_synthetic=False):
    if rule.synthetic and not allow_synthetic:
        raise ValueError("Synthetic fixtures cannot activate real regulatory coverage")
    if not rule.reviewer or not rule.fixture_ids or not all(rule.fixture_results.get(i) is True for i in rule.fixture_ids):
        raise ValueError("Explicit reviewer and passing regression fixtures required")
    if not rule.source_anchor_ids:
        raise ValueError("Original source support required")
    if not rule.fixture_cases:
        raise ValueError("Executable typed regression cases required; supplied pass flags are insufficient")
    for case in rule.fixture_cases:
        if case.get("id") not in rule.fixture_ids:
            raise ValueError("Unregistered rule regression fixture")
        actual = predicate(rule.predicates, case.get("facts", {}))
        exceptions = [predicate(e, case.get("facts", {})) for e in rule.exceptions]
        actual = False if True in exceptions else None if actual is True and None in exceptions else actual
        if actual != case.get("expected"):
            raise ValueError("Rule regression case failed: " + str(case.get("id")))
    for aid in rule.source_anchor_ids:
        anchor = store.one("SELECT d.role FROM anchors a JOIN documents d ON d.id=a.document_id WHERE a.id=?", (aid,))
        if not anchor or anchor["role"] != "original_reference":
            raise ValueError("Report citations cannot activate governing rules")
    if rule.kind == "classification":
        concept = store.one("SELECT family FROM concepts WHERE id=?", (rule.effect.get("class_id"),))
        if not concept or concept["family"] != "BuildingClass":
            raise ValueError("Building classification requires a BuildingClass concept; finish/membrane families cannot substitute")


def evaluate_rules(rules: list[Rule], facts: dict, purpose: str, jurisdiction: str,
                   allow_synthetic=False) -> dict:
    matched = []
    unknown = []
    for rule in rules:
        if rule.state != "active" or rule.jurisdiction != jurisdiction or rule.purpose != purpose:
            continue
        if rule.synthetic and not allow_synthetic:
            continue
        if not rule.reviewer or not rule.source_anchor_ids or not rule.fixture_ids or not all(rule.fixture_results.get(i) for i in rule.fixture_ids):
            continue
        condition = predicate(rule.predicates, facts)
        exceptions = [predicate(e, facts) for e in rule.exceptions]
        if condition is None or (condition is True and None in exceptions):
            unknown.append(rule.id)
        elif condition is True and True not in exceptions:
            matched.append(rule)
    effects = {json.dumps(r.effect, sort_keys=True) for r in matched}
    status = "unresolved" if not matched or unknown or len(effects) != 1 else "supported"
    return {"disposition": status, "effects": [r.effect for r in matched], "rule_ids": [r.id for r in matched],
            "unknown_rules": unknown, "reason": "Conflicting or missing reviewed rule/fact coverage" if status == "unresolved" else "Reviewed typed conditions satisfied"}


def assess(store: Store, context: dict | None, mode: str, allow_synthetic=False, rule_ids=None) -> dict[str, Any]:
    required = ["jurisdiction", "building_use", "approval_pathway", "application_date", "work_scope", "compliance_pathway"]
    facts = json.loads(context["facts"]) if context else {}
    missing = [key for key in required if key not in facts or len(facts[key]) != 1]
    purpose = "proposed_remedial_work" if mode == "remedial" else "original_work_assessment"
    jurisdiction = facts.get("jurisdiction", [{}])[0].get("value", "")
    rules = [Rule.model_validate_json(r["payload"]) for r in store.all("SELECT * FROM rules WHERE state='active'")]
    if rule_ids is not None:
        rules = [r for r in rules if r.id in rule_ids]
    edition_rules = [r for r in rules if r.kind == "edition"]
    class_rules = [r for r in rules if r.kind == "classification"]
    result = evaluate_rules(edition_rules, facts, purpose, jurisdiction, allow_synthetic)
    classification = evaluate_rules(class_rules, facts, purpose, jurisdiction, allow_synthetic)
    result.update({"id": identity("decision", context["id"] if context else None, purpose, result),
                   "context_id": context["id"] if context else None, "purpose": purpose,
                   "missing_conditions": missing, "selected_editions": [], "reference_chains": [],
                   "fact_sources": facts, "classification": classification, "selected_fragment_ids": [], "gaps": []})
    if missing:
        result["disposition"] = "unresolved"
    if result["disposition"] != "supported" or classification["disposition"] != "supported":
        result["gaps"].append("Reviewed edition/classification rule coverage or sourced facts incomplete")
        result["disposition"] = "unresolved"
    if result["effects"] and result["disposition"] == "supported":
        effect = result["effects"][0]
        edition = store.one("SELECT * FROM reference_editions WHERE id=?", (effect.get("edition_id"),))
        fragment_ids = effect.get("fragment_ids", [])
        if not edition or edition["synthetic"] and not allow_synthetic or not fragment_ids:
            result["gaps"].append("Reviewed original edition and complete clause fragments required")
        else:
            for fid in fragment_ids:
                fragment = store.one("SELECT * FROM reference_fragments WHERE id=? AND edition_id=? AND state='original_context_reviewed'", (fid, edition["id"]))
                if not fragment:
                    result["gaps"].append("Missing complete original fragment " + fid)
            from app.references import reference_chain
            chain = reference_chain(store, fragment_ids, facts, allow_synthetic)
            result["reference_chains"] = chain["relationships"]
            result["gaps"] += chain["missing"]
            normative = [r for r in chain["relationships"] if r["basis"] in {"primary", "secondary"}]
            if effect.get("requires_references", True) and not normative:
                result["gaps"].append("Scoped normative reference chain not reviewed")
            if not result["gaps"]:
                result["selected_editions"] = [edition["id"], *sorted({r["to_edition_id"] for r in normative})]
                result["selected_fragment_ids"] = chain["fragment_ids"]
                result["rule_ids"] += classification["rule_ids"]
        if result["gaps"]:
            result["disposition"] = "unresolved"
    if missing:
        result["gaps"].append("Missing/ambiguous project facts: " + ", ".join(missing))
    result["conditional"] = any(v.get("kind") == "user_declaration" for values in facts.values() for v in values)
    if result["conditional"]:
        result["reason"] += "; conditional on attributed user declarations"
    result["id"] = identity("decision", context["id"] if context else None, purpose, {k:v for k,v in result.items() if k!="id"})
    store.insert("decisions", {"id": result["id"], "context_id": result["context_id"], "payload": result})
    return result
