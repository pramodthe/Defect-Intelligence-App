import io
import json
from zipfile import ZipFile
import pytest
from app.contracts import Claim, Rule
from app.ingestion import register, parse_docx, persist_ir, validate_upload, ocr_media
from app.extraction import build_units, reference_mentions
from app.projections import stage, validate_graph
from app.retrieval import search, enumerate_findings, source, media_detail, rrf
from app.verification import verify_claim
from app.applicability import predicate, evaluate_rules, validate_activation
from app.recovery import backup, restore
from app.store import digest
from tests.conftest import synthetic_docx, publish_fixture


def test_docx_originals_mixed_structure_and_occurrences(store, ontology):
    raw = synthetic_docx()
    r = register(raw, "example.docx", "company_report", store)
    duplicate = register(raw, "other-name.docx", "company_report", store)
    assert duplicate["duplicate"] and duplicate["document_id"] == r["document_id"]
    d = store.one("SELECT * FROM documents WHERE id=?", (r["document_id"],))
    ir = parse_docx(store, d)
    persist_ir(store, ir)
    assert store.asset_path(d["asset_id"]).read_bytes() == raw
    assert any(b.kind == "table" for b in ir.blocks)
    assert any("Nested exception" in b.text for b in ir.blocks)
    assert any("😀 e\u0301" in b.text for b in ir.blocks)
    assert all(b.locator.xpath and b.locator.page_index is None for b in ir.blocks)
    media = store.all("SELECT * FROM media")
    assert len(media) == 2 and len({m["asset_id"] for m in media}) == 1
    build_units(store, d["id"], ontology)
    assert store.one("SELECT COUNT(*) n FROM findings")["n"] == 3
    assert store.one("SELECT COUNT(*) n FROM options")["n"] >= 2


def test_source_span_coverage_token_limit_and_no_option_merge(store, ontology):
    r = publish_fixture(store, ontology, synthetic_docx(long=True))
    revisions = store.all("SELECT * FROM chunk_revisions")
    assert all(c["token_count"] <= 480 for c in revisions)
    for unit in store.all("SELECT * FROM units"):
        blocks = store.all("SELECT b.* FROM unit_blocks ub JOIN blocks b ON b.id=ub.block_id WHERE ub.unit_id=?", (unit["id"],))
        for block in blocks:
            if not block["text"].strip():
                continue
            segments = store.all("SELECT s.* FROM chunk_segments s JOIN chunk_revisions r ON r.id=s.revision_id JOIN chunks c ON c.id=r.chunk_id WHERE c.unit_id=? AND s.block_id=? ORDER BY s.start_cp", (unit["id"], block["id"]))
            assert segments[0]["start_cp"] == 0 and segments[-1]["end_cp"] == len(block["text"])
            assert all(a["end_cp"] == b["start_cp"] for a, b in zip(segments, segments[1:], strict=False))
    for c in revisions:
        segments = store.all("SELECT s.*,b.text FROM chunk_segments s JOIN blocks b ON b.id=s.block_id WHERE revision_id=? ORDER BY s.sequence", (c["id"],))
        assert c["raw_body"] == "\n".join(s["text"][s["start_cp"]:s["end_cp"]] for s in segments)
        assert digest(json.loads(c["metadata"])) == c["metadata_hash"]
        assert not ("Option 1:" in c["raw_body"] and "Option 2:" in c["raw_body"])
    result = search(store, ontology, "soil line")
    assert result["items"] and any("bm25" in e["retrieval_methods"] for e in result["items"])
    assert source(store, result["items"][0]["anchor_ids"][0])["document_id"] == r["document_id"]


def test_class_catalog_ambiguity_and_source_years(ontology):
    assert len(ontology.exact_alias("class 2")) == 3
    assert {c["family"] for c in ontology.resolve("Class 2", "Concrete finish") } == {"ConcreteFinishClass"}
    assert {c["family"] for c in ontology.resolve("Class 2", "Membrane class 2") } == {"MembraneClass"}
    refs = reference_mentions("AS 4654.2—2012, AS 3600:2009 and AS 3600 2018. NCC 2016 Volume Three")
    assert {(r["family"], r["part"], r["year"]) for r in refs} >= {("AS 4654", "2", "2012"), ("AS 3600", None, "2009"), ("AS 3600", None, "2018")}
    assert refs[-1]["volume"] == "Three"


def test_manifest_failure_and_graph_grounding(store, ontology):
    r = publish_fixture(store, ontology)
    old = store.active_manifest()
    class FailingProjection:
        def write(self, revision, batch):
            raise RuntimeError("Injected projection failure")
    with pytest.raises(RuntimeError):
        stage(store, r["document_id"], ontology, graph=FailingProjection())
    assert store.active_manifest() == old
    assert search(store, ontology, "membrane")["items"]
    batch = validate_graph(store, r["document_id"], ontology)
    assert any(n["kind"] == "Assertion" for n in batch["nodes"])
    assertion = store.one("SELECT * FROM assertions LIMIT 1")
    store.execute("DELETE FROM assertion_support WHERE assertion_id=?", (assertion["id"],))
    with pytest.raises(ValueError, match="Unsupported"):
        validate_graph(store, r["document_id"], ontology)


def test_mechanical_verification_rejects_fabrication_and_governing(store, ontology):
    publish_fixture(store, ontology)
    result = search(store, ontology, "membrane")
    fake = Claim(text="Invented", kind="report_excerpt", anchor_ids=["missing"])
    assert not verify_claim(store, fake, result["manifest_id"], result["items"])["accepted"]
    supported = result["items"][0]
    claim = Claim(text="Current rule", kind="governing", anchor_ids=supported["anchor_ids"], edition_id="latest")
    assert not verify_claim(store, claim, result["manifest_id"], result["items"], {"id":"d", "disposition":"unresolved"})["accepted"]
    quote = source(store, supported["anchor_ids"][0])["quote"]
    assert verify_claim(store, Claim(text="Source", kind="report_excerpt", anchor_ids=[supported["anchor_ids"][0]], quote=quote), result["manifest_id"], result["items"])["accepted"]


@pytest.mark.parametrize("expr,facts,expected", [
    ({"field":"date","op":"lt","value":"2016-01-01"},{},None),
    ({"field":"date","op":"lt","value":"2016-01-01"},{"date":"2015-01-01"},True),
    ({"all":[{"field":"date","op":"exists"},{"field":"class","op":"eq","value":"2"}]},{"class":"3"},False),
    ({"any":[{"field":"date","op":"exists"},{"field":"class","op":"eq","value":"2"}]},{"class":"2"},True),
    ({"field":"class","op":"eq","value":"2"},{"class":[{"value":"2"},{"value":"5"}]},None)
])
def test_three_valued_rules(expr,facts,expected):
    assert predicate(expr,facts) is expected


def test_synthetic_rules_do_not_become_real_coverage(store):
    rule = Rule(id="test-old",version=1,kind="edition",jurisdiction="TEST",purpose="original",predicates={"field":"approval","op":"lt","value":"2016-01-01"},effect={"edition":"E_old"},source_anchor_ids=["test-source"],fixture_ids=["f"],fixture_results={"f":True},reviewer="test reviewer",state="active",synthetic=True)
    facts = {"approval":"2015-01-01","report_date":"2026-10-12"}
    assert evaluate_rules([rule],facts,"original","TEST")["disposition"] == "unresolved"
    assert evaluate_rules([rule],facts,"original","TEST",allow_synthetic=True)["effects"] == [{"edition":"E_old"}]
    conflicting = rule.model_copy(update={"id":"other", "effect":{"edition":"E_new"}})
    assert evaluate_rules([rule,conflicting],facts,"original","TEST",allow_synthetic=True)["disposition"] == "unresolved"
    with pytest.raises(ValueError,match="Synthetic"):
        validate_activation(rule,store)


def test_upload_boundary_archive_and_backup_restore(store, ontology):
    with pytest.raises(ValueError):
        validate_upload(b"bad", "bad.pdf", store)
    buf=io.BytesIO()
    with ZipFile(buf,"w") as z:
        z.writestr("../evil", "bad")
        z.writestr("word/document.xml","bad")
    with pytest.raises(ValueError,match="Unsafe"):
        validate_upload(buf.getvalue(),"bad.docx",store)
    r=publish_fixture(store,ontology)
    evidence=search(store,ontology,"membrane")["items"][0]
    manifest=store.active_manifest()
    b=backup(store)
    store.archive(r["document_id"])
    assert not search(store,ontology,"membrane")["items"]
    assert source(store,evidence["anchor_ids"][0])
    restored=restore(store,b["id"])
    assert store.all('SELECT document_id FROM manifest_members WHERE manifest_id=?',(restored['manifest_id'],))==store.all('SELECT document_id FROM manifest_members WHERE manifest_id=?',(manifest,))
    assert search(store,ontology,"membrane")["items"]


def test_complete_enumeration_exceeds_top_k(store,ontology):
    publish_fixture(store,ontology,synthetic_docx(count=41))
    first=enumerate_findings(store,"planter",limit=30)
    second=enumerate_findings(store,"planter",offset=int(first["next_cursor"]),limit=30)
    assert first["total"]==41 and len(first["items"])+len(second["items"])==41
    assert "limited" in first["coverage"]
    assert rrf([["a","b"],["b","c"]])[0]=="b"


def test_real_local_ocr_on_synthetic_image(store,ontology):
    r=register(synthetic_docx(),"ocr.docx","company_report",store)
    doc=store.one("SELECT * FROM documents WHERE id=?",(r["document_id"],))
    persist_ir(store,parse_docx(store,doc))
    ocr_media(store,r["document_id"],r["job_id"])
    texts=store.all("SELECT * FROM visuals")
    assert len(texts)==2 and all(v["method"]=="rapidocr" for v in texts)
    assert any("4654" in v["text"] and "2.17" in v["text"] for v in texts)
    build_units(store,doc["id"],ontology)
    m=media_detail(store,store.one("SELECT id FROM media LIMIT 1")["id"])
    assert m["identity"]["original_verification"]=="embedded_extract_only"
