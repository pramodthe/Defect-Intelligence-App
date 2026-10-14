import io
import pytest
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from app.ingestion import register, parse_pdf, persist_ir, normalize_pdf_box
from app.projections import LocalEmbedding
from app.settings import ROOT


def pdf_fixture(scanned=False,rotation=0):
    image=Image.new('RGB',(900,300),'white')
    ImageDraw.Draw(image).text((20,20),'AS 4654.2-2012 Figure 2.17',fill='black',font_size=30)
    out=io.BytesIO()
    c=canvas.Canvas(out,pagesize=(600,800))
    c.setPageRotation(rotation)
    if not scanned:
        c.drawString(50,740,'Native narrative with an image-only reference below.')
    c.drawImage(ImageReader(image),50,400,width=500,height=200)
    c.showPage()
    c.save()
    return out.getvalue()


@pytest.mark.parametrize('scanned,rotation',[(False,0),(False,90),(True,0)])
def test_pdf_native_scan_rotation_and_embedded_original_stream(store,scanned,rotation):
    raw=pdf_fixture(scanned,rotation)
    r=register(raw,'fixture.pdf','company_report',store)
    doc=store.require('SELECT * FROM documents WHERE id=?',(r['document_id'],))
    ir=parse_pdf(store,doc)
    persist_ir(store,ir)
    assert store.asset_path(doc['asset_id']).read_bytes()==raw
    assert any(b.kind=='picture_occurrence' and not b.payload.get('rendered_region') for b in ir.blocks)
    assert any(b.payload.get('raw_stream_asset_id') for b in ir.blocks)
    assert all(b.locator.page_index==0 for b in ir.blocks)
    assert all(0<=x<=1 for b in ir.blocks for x in b.locator.normalized_bbox)
    assert all(b.locator.rotation==rotation for b in ir.blocks)
    if not scanned:
        assert any('Native narrative' in b.text for b in ir.blocks)


def test_rotated_cropped_normalized_bounds():
    box=[20,30,220,430]
    bounds=[20,330,120,430]
    assert normalize_pdf_box(bounds,box,0)==[0,.0,.5,.25]
    assert normalize_pdf_box(bounds,box,90)==[.75,0,1,.5]


@pytest.mark.skipif(not (ROOT/'data/model-profile.json').exists(),reason='Explicit BGE model cache setup required')
def test_actual_bge_dimensions_normalization_and_local_qdrant(store):
    import json
    from qdrant_client import QdrantClient, models
    profile=json.loads((ROOT/'data/model-profile.json').read_text('utf-8'))
    if not profile['weights_present']:
        pytest.skip('BGE weights are not cached')
    store.config.embedding_path=profile['cache_path']
    store.config.tokenizer_path=profile['cache_path']
    embeddings=LocalEmbedding(store)
    vectors=embeddings.encode(['Planter box membrane termination and drainage overflow.','Fire resistance of an internal door.'])
    assert len(vectors)==2 and all(len(v)==768 for v in vectors)
    assert all(abs(sum(x*x for x in v)-1)<.0001 for v in vectors)
    client=QdrantClient(path=str(store.root/'qdrant-test'))
    client.create_collection('fixture',vectors_config=models.VectorParams(size=768,distance=models.Distance.COSINE))
    client.upsert('fixture',[models.PointStruct(id=i+1,vector=v,payload={'evidence_id':str(i),'scope':'synthetic'}) for i,v in enumerate(vectors)],wait=True)
    query=embeddings.encode(['Represent this sentence for searching relevant passages: waterproofing details for a planter'])[0]
    hits=client.query_points('fixture',query=query,limit=2).points
    assert hits[0].id==1
    client.close()
