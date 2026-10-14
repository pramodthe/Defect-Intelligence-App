import io
from reportlab.pdfgen import canvas
from app.ingestion import register,parse_pdf,persist_ir
from app.extraction import build_units,annotate_domain
from app.chunking import build_chunks
from app.projections import stage
from app.retrieval import enumerate_findings,source
from app.renditions import confirm,RenditionReview
from tests.conftest import publish_fixture


def test_reviewed_renditions_keep_separate_sources_without_double_count(store,ontology):
    first=publish_fixture(store,ontology)
    d=store.require('SELECT * FROM documents WHERE id=?',(first['document_id'],))
    out=io.BytesIO()
    c=canvas.Canvas(out)
    c.drawString(50,750,'Sample Findings:')
    c.drawString(50,725,'DS-1, Unit 1 planter')
    c.drawString(50,700,'Membrane termination requires inspection.')
    c.save()
    second=register(out.getvalue(),'synthetic-rendition.pdf','company_report',store,family_id=d['family_id'])
    pdf=store.require('SELECT * FROM documents WHERE id=?',(second['document_id'],))
    persist_ir(store,parse_pdf(store,pdf))
    build_units(store,pdf['id'],ontology)
    annotate_domain(store,pdf['id'],ontology)
    build_chunks(store,pdf['id'],ontology.version)
    projection=stage(store,pdf['id'],ontology)
    store.activate(projection['projection_id'],{'profile':projection['profile']})
    before=enumerate_findings(store,'')
    assert before['total']==4
    canonical=store.require("SELECT * FROM findings WHERE document_id=? AND identifier='DS-1'",(d['id'],))
    alias=store.require("SELECT * FROM findings WHERE document_id=? AND identifier='DS-1'",(pdf['id'],))
    result=confirm(store,RenditionReview(canonical_finding_id=canonical['id'],alias_finding_id=alias['id'],anchor_ids=[canonical['anchor_id'],alias['anchor_id']],reviewer='Synthetic identity reviewer',reason='Controlled same-version Word/PDF fixture identity',same_report_version=True))
    assert result['state']=='confirmed' and enumerate_findings(store,'')['total']==3
    assert source(store,canonical['anchor_id'])['locator']['format']=='docx'
    assert source(store,alias['anchor_id'])['locator']['format']=='pdf'
    store.archive(d['id'])
    assert enumerate_findings(store,'')['total']==1
