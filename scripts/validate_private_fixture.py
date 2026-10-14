"""Local pilot audit. Detailed private results stay under data/qa, never in source control."""
import json
import time
import uuid
from zipfile import ZipFile
import httpx
from app.settings import settings,ROOT
from app.store import Store,digest
from app.chunking import TokenCounter
from app.ontology import Ontology
from app.retrieval import manifest_chunks,evidence_media

store=Store(settings)
original=ROOT.parent/'sample expert report.docx'
sha=digest(original.read_bytes())
doc=store.require('SELECT * FROM documents WHERE sha256=?',(sha,))
with ZipFile(original) as z:
    media=[n for n in z.namelist() if n.startswith('word/media/') and not n.endswith('/')]
    missing=[]
    for name in media:
        raw=z.read(name)
        asset=store.one('SELECT id FROM assets WHERE sha256=?',(digest(raw),))
        if not asset or store.asset_path(asset['id']).read_bytes()!=raw:
            missing.append(name)
assert len(media)==244 and not missing
ids,projections=manifest_chunks(store,store.active_manifest())
counter=TokenCounter(settings.tokenizer_path)
invalid=[]
for cid in ids:
    c=store.require('SELECT * FROM chunk_revisions WHERE id=?',(cid,))
    segments=store.all('SELECT s.*,b.text FROM chunk_segments s JOIN blocks b ON b.id=s.block_id WHERE revision_id=? ORDER BY s.sequence',(cid,))
    body='\n'.join(s['text'][s['start_cp']:s['end_cp']] for s in segments)
    if body!=c['raw_body'] or counter.count(c['retrieval_text'])>480 or digest(json.loads(c['metadata']))!=c['metadata_hash']:
        invalid.append(cid)
assert not invalid
visual=evidence_media(store,Ontology(store),'AS 4654.2-2012 Figure 2.17',limit=1)['items'][0]
assert visual['identity']['source_printed_page']=='30'
assert visual['locator']['format']=='docx' and visual['locator']['page_index'] is None
assert visual['reasoning']
latencies=[]
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=180) as client:
    for _ in range(10):
        start=time.monotonic()
        response=client.get('/api/findings',params={'q':'Planter'})
        response.raise_for_status()
        latencies.append(time.monotonic()-start)
    start=time.monotonic()
    run=client.post('/api/questions',headers={'X-Workspace-Request':'1'},json={'question':'Find previous planter box membrane reasoning and remediation with the original Figure 2.17','mode':'historical','client_request_id':str(uuid.uuid4())}).json()
    run_id=run['run_id']
    while time.monotonic()-start<180:
        result=client.get('/api/runs/'+run_id).json()
        if result['status'] not in {'queued','running'}:
            break
        time.sleep(.25)
    assert result['status']=='partial' and result['answer']['claims']
    for claim in result['answer']['claims']:
        for anchor in claim['anchor_ids']:
            assert client.get('/api/source-anchors/'+anchor).status_code==200
    research_seconds=time.monotonic()-start
report={'fixture':'private-docx/1','original_sha256':sha,'original_unchanged':digest(original.read_bytes())==sha,
    'embedded_assets_expected':244,'embedded_assets_preserved':len(media),'missing_assets':missing,
    'media_occurrences':store.require('SELECT COUNT(*) n FROM media WHERE document_id=?',(doc['id'],))['n'],
    'structure_blocks':store.require("SELECT COUNT(*) n FROM blocks WHERE document_id=? AND content_kind<>'ocr_text'",(doc['id'],))['n'],
    'published_chunk_revisions':len(ids),'invalid_spans_or_tokens':invalid,'figure_media_id':visual['id'],
    'figure_original_asset_id':visual['asset_id'],'source_printed_page':'30','report_locator':visual['locator'],
    'manifest_id':store.active_manifest(),'projections':[{'id':p['id'],'profile':p['profile'],'receipts':json.loads(p['receipts'])} for p in projections],
    'search_seconds':latencies,'search_p95_seconds':sorted(latencies)[-1],'research_run_id':run_id,
    'research_seconds':research_seconds,'research_outcome':result['status'],'accepted_excerpt_claims':len(result['answer']['claims']),
    'regulatory_coverage':'none activated; no real applicability endorsement','evaluation_scope':'one private sample; not the 50-question reviewed pilot'}
target=ROOT/'data/qa/private-fixture-results.json'
target.write_text(json.dumps(report,indent=2),'utf-8')
print(json.dumps({k:report[k] for k in ['original_unchanged','embedded_assets_preserved','media_occurrences','published_chunk_revisions','search_p95_seconds','research_seconds','research_outcome','accepted_excerpt_claims']},indent=2))
