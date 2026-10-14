import io
import json

import pytest
from docx import Document
from langchain_core.messages import AIMessage, ToolMessage

from app.contracts import DraftAnswer, EvidenceGrade, ClarificationPlan, FactResponse
from app.drafting import applicable_requirements, validate_chat_response
from app.providers import SupportVerdict
from app.research_tools import tool_registry
from app.store import canonical
from app.workflows import build_research, checkpoint_session, execute_research
from tests.conftest import publish_fixture, synthetic_docx
from tests.test_workflows_api import run_record


def bathroom_fixture(store, ontology):
    doc = Document(io.BytesIO(synthetic_docx()))
    for p in doc.paragraphs:
        p.text = p.text.replace('Planter Box Membrane', 'Bathroom Waterproofing').replace('planter', 'bathroom').replace('Membrane does not extend above the soil line.', 'Water escapes at the bathroom doorway.')
    raw = io.BytesIO()
    doc.save(raw)
    return publish_fixture(store, ontology, raw.getvalue())


def drafting_run(store):
    rid = run_record(store, 'draft')
    store.execute('UPDATE runs SET question=? WHERE id=?', ('water ingress from the bathroom', rid))
    store.insert('run_drafting', {'run_id': rid, 'facts': {}})
    return rid


class DraftPlanner:
    receipt = {'transport': 'test_double'}

    def __init__(self):
        self.calls = 0

    async def generate_structured(self, schema, messages, budget):
        assert schema is ClarificationPlan
        conversation = json.loads(messages[-1]['content'])['conversation']
        if len(conversation) == 1:
            return ClarificationPlan(sufficient=False, message='Which state, building class and BCA/NCC edition should I use?',
                questions=[{'key': key, 'question': key.replace('_', ' ')+'?'} for key in ('jurisdiction', 'building_class', 'code_edition')])
        return ClarificationPlan(sufficient=True, message='I can draft from historical sources while keeping the unknown details explicit.',
            extracted_facts=[{'key': key, 'value': 'Unknown', 'evidence_quote': 'All details Unknown'} for key in ('jurisdiction', 'building_class', 'code_edition')])

    async def choose_tools(self, messages, tools, budget):
        self.calls += 1
        if self.calls == 1:
            assert 'project_facts' in messages[1].content and 'Unknown' in messages[1].content
            return AIMessage(content='', tool_calls=[{'id': 'search-bath', 'name': 'search_precedents',
                'args': {'query': 'bathroom water reasoning remediation'}, 'type': 'tool_call'}])
        results = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
        iid = next(e['metadata']['defect_item_id'] for r in results for e in r.get('items', []) if e['metadata'].get('defect_item_id'))
        return AIMessage(content='', tool_calls=[{'id': 'read-section', 'name': 'get_report_sections', 'args': {'item_ids': [iid]}, 'type': 'tool_call'}])


class Grade:
    receipt = {'transport': 'test_double'}

    async def generate_structured(self, schema, messages, budget):
        assert schema is EvidenceGrade
        return EvidenceGrade(sufficient=True)


class DraftWriter:
    receipt = {'transport': 'test_double'}

    async def generate_structured(self, schema, messages, budget):
        assert schema is DraftAnswer
        payload = json.loads(messages[-1]['content'])
        item = next(s for s in payload['sources'] if 'Water escapes' in s['quote'])
        return DraftAnswer(claims=[{'text': 'The previous report records water escaping at a bathroom doorway.', 'kind': 'report_excerpt',
            'anchor_ids': [item['id']], 'quote': 'Water escapes at the bathroom doorway.', 'draft_section': 'assessment'},
            {'text': 'This project breaches BCA F1.7.', 'kind': 'inference', 'anchor_ids': [item['id']],
             'quote': 'Water escapes at the bathroom doorway.', 'draft_section': 'opinion'},
            {'text': 'The user declared a Class 2 building.', 'kind': 'inference', 'anchor_ids': [item['id']],
             'quote': 'Water escapes at the bathroom doorway.', 'draft_section': 'observation'}], selected_media_ids=['invented-image'])


class CheckSupport:
    receipt = {'transport': 'test_double'}

    async def generate_structured(self, schema, messages, budget):
        assert schema is SupportVerdict
        claims = json.loads(messages[-1]['content'])['claims']
        assert len(claims) == 1 and 'breaches' not in claims[0]['text']
        return SupportVerdict(supported_claim_indexes=[0], gaps=[])


@pytest.mark.asyncio
async def test_short_issue_pauses_then_durable_answers_grade_retrieve_draft(store, ontology):
    bathroom_fixture(store, ontology)
    store.config.text_model = store.config.verifier_model = 'fixture-model'
    store.config.active_seconds = 300
    rid = drafting_run(store)
    planner = DraftPlanner()
    async with checkpoint_session(store) as saver:
        await execute_research(store, build_research(store, saver, ontology, DraftWriter(), CheckSupport(), planner, Grade()), rid)
    assert store.require('SELECT status FROM runs WHERE id=?', (rid,))['status'] == 'clarification_required'
    assert planner.calls == 0  # Intake can call the model; retrieval must wait for clarification.
    payload = json.loads(store.require("SELECT payload FROM events WHERE owner_id=? AND type='clarification_required'", (rid,))['payload'])
    assert {q['key'] for q in payload['questions']} == {'jurisdiction', 'building_class', 'code_edition'}
    assert 'assessment_scope' not in payload['missing']
    # Persist the submitted response, then reopen the checkpoint connection as after a restart.
    store.execute('UPDATE run_drafting SET pending_response=? WHERE run_id=?', (canonical({'expected_context_version': 1, 'message': 'All details Unknown', 'provenance': 'Synthetic UI test declarations'}), rid))
    async with checkpoint_session(store) as saver:
        await execute_research(store, build_research(store, saver, ontology, DraftWriter(), CheckSupport(), planner, Grade()), rid)
    row = store.require('SELECT * FROM runs WHERE id=?', (rid,))
    assert row['status'] == 'partial' and row['error'] is None
    answer = json.loads(row['answer'])
    assert len(answer['claims']) == 1 and answer['draft']['status'] == 'needs_technical_review'
    assert answer['draft']['media'] == [] and answer['draft']['requirements_coverage'] == 'unresolved'
    assert all(f['value'] == 'Unknown' for f in answer['draft']['facts'].values())
    assert len(json.loads(store.require('SELECT conversation FROM run_drafting WHERE run_id=?', (rid,))['conversation'])) == 4
    assert any('Generated inference omitted' in gap for gap in answer['gaps'])
    assert planner.calls == 2  # A model saying sufficient cannot bypass the complete-section gate.
    assert any(c['node'] == 'model_evidence_grade' for c in answer['model_calls'])
    assert all(op['tool_cost'] == 0 for op in store.all("SELECT tool_cost FROM operations WHERE owner_id=? AND node LIKE 'model_%'", (rid,)))
    assert any(c['payload']['tool'] == 'get_report_sections' for c in answer['tool_calls'])
    before = store.require('SELECT COUNT(*) n FROM operations WHERE owner_id=?', (rid,))['n']
    async with checkpoint_session(store) as saver:
        await execute_research(store, build_research(store, saver, ontology, DraftWriter(), CheckSupport(), planner, Grade()), rid)
    assert store.require('SELECT COUNT(*) n FROM operations WHERE owner_id=?', (rid,))['n'] == before


def test_empty_reply_rejected_and_free_form_response_accepted():
    record = {'clarification': {'questions': [{'key': 'building_class'}]}}
    with pytest.raises(ValueError, match='Reply to the assistant'):
        validate_chat_response(record, FactResponse(expected_context_version=1, provenance='Test attribution'))
    validate_chat_response(record, FactResponse(expected_context_version=1, message='Class 2, NSW, NCC 2019', provenance='Test attribution'))


@pytest.mark.asyncio
async def test_adequate_initial_question_skips_follow_up_and_rejects_invented_fact_extraction(store, ontology):
    bathroom_fixture(store, ontology)
    store.config.text_model = store.config.verifier_model = 'fixture-model'
    store.config.active_seconds = 300
    rid = drafting_run(store)
    store.execute('UPDATE runs SET question=? WHERE id=?', ('water ingress from the bathroom in NSW, Class 2, NCC 2019', rid))
    class AdequatePlanner(DraftPlanner):
        async def generate_structured(self, schema, messages, budget):
            return ClarificationPlan(sufficient=True, message='I have enough information to research a draft.',
                extracted_facts=[{'key': 'jurisdiction', 'value': 'NSW', 'evidence_quote': 'NSW'},
                                 {'key': 'building_class', 'value': 'Class 2', 'evidence_quote': 'Class 2'},
                                 {'key': 'code_edition', 'value': 'NCC 2019', 'evidence_quote': 'NCC 2019'},
                                 {'key': 'observations', 'value': 'A moisture reading of 99%', 'evidence_quote': 'NSW'}])
        async def choose_tools(self, messages, tools, budget):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='', tool_calls=[{'id': 'search-bath', 'name': 'search_precedents', 'args': {'query': 'bathroom water reasoning remediation'}, 'type': 'tool_call'}])
            results = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
            iid = next(e['metadata']['defect_item_id'] for r in results for e in r.get('items', []) if e['metadata'].get('defect_item_id'))
            return AIMessage(content='', tool_calls=[{'id': 'read-section', 'name': 'get_report_sections', 'args': {'item_ids': [iid]}, 'type': 'tool_call'}])
    async with checkpoint_session(store) as saver:
        await execute_research(store, build_research(store, saver, ontology, DraftWriter(), CheckSupport(), AdequatePlanner(), Grade()), rid)
    assert not store.one("SELECT sequence FROM events WHERE owner_id=? AND type='clarification_required'", (rid,))
    facts = json.loads(store.require('SELECT facts FROM run_drafting WHERE run_id=?', (rid,))['facts'])
    assert facts['building_class']['value'] == 'Class 2' and 'observations' not in facts


def test_exact_requirements_only_from_supported_pinned_originals(store, ontology):
    from app.ingestion import register, parse_docx, persist_ir
    from app.extraction import build_units, annotate_domain
    from app.chunking import build_chunks
    from app.projections import stage
    from app.references import review_edition, review_fragment
    from app.contracts import EditionReview, FragmentReview
    registered = register(synthetic_docx(), 'fixture-original.docx', 'original_reference', store)
    doc = store.require('SELECT * FROM documents WHERE id=?', (registered['document_id'],))
    persist_ir(store, parse_docx(store, doc))
    build_units(store, doc['id'], ontology)
    annotate_domain(store, doc['id'], ontology)
    build_chunks(store, doc['id'], ontology.version)
    projected = stage(store, doc['id'], ontology)
    store.activate(projected['projection_id'], {})
    anchor = store.require('SELECT id FROM anchors WHERE document_id=? AND end_cp>0 LIMIT 1', (doc['id'],))['id']
    edition = review_edition(store, EditionReview(document_id=doc['id'], family='FIXTURE', year='2022', amendments=[], reviewer='Synthetic test reviewer', anchor_ids=[anchor]))
    fragment = review_fragment(store, FragmentReview(edition_id=edition['id'], kind='clause', identifier='TEST', anchor_ids=[anchor]))
    rid = drafting_run(store)
    decision = {'id': 'fixture-decision', 'disposition': 'supported', 'selected_fragment_ids': [fragment['id']]}
    store.insert('decisions', {'id': decision['id'], 'payload': decision})
    store.execute('UPDATE run_drafting SET decision_id=? WHERE run_id=?', (decision['id'], rid))
    manifest = store.active_manifest()
    result = tool_registry(store, ontology, manifest, rid)['get_applicable_requirements'].invoke({})
    assert result['coverage'] == 'supported' and result['items'][0]['anchor_ids'] == [anchor]
    assert result['items'][0]['metadata']['edition_id'] == edition['id']
    store.execute('UPDATE reference_editions SET synthetic=1 WHERE id=?', (edition['id'],))
    assert applicable_requirements(store, rid, manifest)['coverage'] == 'incomplete'
    store.execute('UPDATE decisions SET payload=? WHERE id=?', (canonical({**decision, 'disposition': 'unresolved'}), decision['id']))
    assert applicable_requirements(store, rid, manifest)['items'] == []
