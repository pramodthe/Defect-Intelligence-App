import time
from app.applicability import assess
from app.contracts import EditionReview, FragmentReview, ReferenceReview, Rule
from app.references import review_edition, review_fragment, review_relationship, reference_chain
from app.ingestion import register,parse_docx,persist_ir
from tests.conftest import synthetic_docx


def test_exact_part_amendment_chain_and_separate_remedial_context(store):
    r=register(synthetic_docx(),'synthetic-original-reference.docx','original_reference',store)
    doc=store.require('SELECT * FROM documents WHERE id=?',(r['document_id'],))
    persist_ir(store,parse_docx(store,doc))
    anchor=store.require("SELECT id FROM anchors WHERE document_id=? AND end_cp>0 LIMIT 1",(r['document_id'],))['id']
    code=review_edition(store,EditionReview(document_id=doc['id'],family='NCC',year='2016',volume='One',amendments=['A1'],reviewer='Synthetic fixture reviewer',anchor_ids=[anchor],synthetic=True))
    standard=review_edition(store,EditionReview(document_id=doc['id'],family='AS 4654',part='2',year='2016',amendments=['A2'],reviewer='Synthetic fixture reviewer',anchor_ids=[anchor],synthetic=True))
    newer=review_edition(store,EditionReview(document_id=doc['id'],family='AS 4654',part='1',year='2022',amendments=[],reviewer='Synthetic fixture reviewer',anchor_ids=[anchor],synthetic=True))
    fragment=review_fragment(store,FragmentReview(edition_id=code['id'],kind='clause',identifier='F.test',anchor_ids=[anchor]))
    review_relationship(store,ReferenceReview(from_fragment_id=fragment['id'],to_edition_id=standard['id'],basis='primary',scope='Synthetic planter fixture only',predicates={'field':'topic','op':'eq','value':'planter'},anchor_ids=[anchor],reviewer='Synthetic fixture reviewer'))
    facts={key:[{'value':value,'kind':'user_declaration','provenance':'Synthetic fixture'}] for key,value in {'jurisdiction':'TEST','building_use':'residential','approval_pathway':'fixture','application_date':'2015-01-01','work_scope':'original','compliance_pathway':'DTS','topic':'planter'}.items()}
    store.insert('projects',{'id':'p','label':'Synthetic','version':1})
    store.insert('contexts',{'id':'ctx','project_id':'p','purpose':'original_work_assessment','version':1,'facts':facts,'created':time.time()})
    common={'version':1,'jurisdiction':'TEST','purpose':'original_work_assessment','source_anchor_ids':[anchor],'fixture_ids':['test-case'],'fixture_results':{'test-case':True},'reviewer':'Synthetic reviewer','state':'active','synthetic':True}
    edition_rule=Rule(id='fixture-edition',kind='edition',predicates={'field':'application_date','op':'lt','value':'2016-01-01'},effect={'edition_id':code['id'],'fragment_ids':[fragment['id']]},**common)
    class_rule=Rule(id='fixture-class',kind='classification',predicates={'field':'building_use','op':'eq','value':'residential'},effect={'class_id':'building.class2'},**common)
    for rule in [edition_rule,class_rule]:
        store.insert('rules',{'id':rule.id,'version':1,'payload':rule.model_dump(mode='json'),'state':'active'})
    ctx=store.require('SELECT * FROM contexts WHERE id="ctx"')
    assert assess(store,ctx,'current')['disposition']=='unresolved'
    decision=assess(store,ctx,'current',allow_synthetic=True)
    assert decision['disposition']=='supported'
    assert standard['id'] in decision['selected_editions'] and newer['id'] not in decision['selected_editions']
    assert decision['reference_chains'][0]['amendments']==['A2']
    assert assess(store,ctx,'remedial',allow_synthetic=True)['disposition']=='unresolved'
    assert reference_chain(store,[fragment['id']],{},allow_synthetic=True)['missing']
