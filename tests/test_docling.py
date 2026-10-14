import pytest
from app.ingestion import register,parse_pdf,persist_ir
from app.settings import ROOT
from tests.test_pdf_vectors import pdf_fixture


@pytest.mark.skipif(not (ROOT/'data/docling-profile.json').exists(),reason='Explicit local Docling artifact cache required')
def test_actual_docling_local_layout_and_provenance(store):
    store.config.docling_artifacts_path=str(ROOT/'.cache/models/docling')
    r=register(pdf_fixture(),'docling-layout.pdf','company_report',store)
    d=store.require('SELECT * FROM documents WHERE id=?',(r['document_id'],))
    ir=parse_pdf(store,d)
    assert ir.parser_profile_id=='docling-pdf/1'
    assert any(b.payload.get('docling_ref') for b in ir.blocks)
    assert any('Native narrative' in b.text for b in ir.blocks)
    persist_ir(store,ir)
