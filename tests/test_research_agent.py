import json
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from app.contracts import DraftAnswer
from app.providers import SupportVerdict, text_credential, language_model, apply_saved_text_settings
from app.research_tools import tool_registry
from app.settings import Settings
from app.workflows import checkpoint_session, build_research, execute_research
from tests.conftest import publish_fixture
from tests.test_workflows_api import run_record


class Planner:
    receipt = {'transport': 'test_double'}

    def __init__(self):
        self.calls = 0

    async def choose_tools(self, messages, tools, budget):
        self.calls += 1
        assert 'search_precedents' in {t.name for t in tools}
        if self.calls == 1:
            return AIMessage(content='', tool_calls=[{'id': 'search-1', 'name': 'search_precedents',
                             'args': {'query': 'planter membrane reasoning repair'}, 'type': 'tool_call'}])
        if self.calls == 2:
            result = json.loads(next(m.content for m in messages if isinstance(m, ToolMessage)))
            anchor = result['items'][0]['anchor_ids'][0]
            return AIMessage(content='', tool_calls=[{'id': 'source-1', 'name': 'get_exact_source',
                             'args': {'anchor_id': anchor}, 'type': 'tool_call'}])
        return AIMessage(content='Evidence inspected; ready to draft.')


class Synthesis:
    receipt = {'transport': 'test_double'}

    def __init__(self, store):
        self.store = store

    async def generate_structured(self, schema, messages, budget):
        assert schema is DraftAnswer
        payload = json.loads(messages[-1]['content'])
        e = payload['evidence'][0]
        anchor = e['anchor_ids'][0]
        quote = next(s['quote'] for s in payload['sources'] if s['id'] == anchor)
        return DraftAnswer.model_validate({'claims': [{'text': 'The report records the cited passage.',
                    'kind': 'report_excerpt', 'anchor_ids': [anchor], 'quote': quote}]})


class Verifier:
    receipt = {'transport': 'test_double'}

    async def generate_structured(self, schema, messages, budget):
        assert schema is SupportVerdict
        return SupportVerdict(supported_claim_indexes=[0], gaps=[])


@pytest.mark.asyncio
async def test_agent_executes_langchain_tools_and_persists_receipts(store, ontology):
    publish_fixture(store, ontology)
    store.config.text_provider = 'compatible'
    store.config.text_model = store.config.verifier_model = 'fixture-model'
    planner = Planner()
    rid = run_record(store)
    async with checkpoint_session(store) as saver:
        graph = build_research(store, saver, ontology, Synthesis(store), Verifier(), planner)
        await execute_research(store, graph, rid)
    run = store.require('SELECT * FROM runs WHERE id=?', (rid,))
    assert run['error'] is None
    assert json.loads(run['answer'])['claims']
    assert all(a.startswith('anchor_') for c in json.loads(run['answer'])['claims'] for a in c['anchor_ids'])
    assert planner.calls == 3
    events = [json.loads(e['payload']) for e in store.all("SELECT payload FROM events WHERE owner_id=? AND type='tool_completed'", (rid,))]
    assert [e['tool'] for e in events] == ['search_precedents', 'get_exact_source']
    assert len(json.loads(run['answer'])['model_calls']) == 5
    assert json.loads(run['evidence'])['sources']
    count = store.require('SELECT COUNT(*) n FROM operations WHERE owner_id=?', (rid,))['n']
    async with checkpoint_session(store) as saver:
        await execute_research(store, build_research(store, saver, ontology, Synthesis(store), Verifier(), planner), rid)
    assert planner.calls == 3
    assert store.require('SELECT COUNT(*) n FROM operations WHERE owner_id=?', (rid,))['n'] == count


def test_tools_cannot_fetch_unpublished_document(store, ontology):
    old = store.active_manifest()
    publish_fixture(store, ontology)
    anchor = store.require('SELECT id FROM anchors LIMIT 1')['id']
    with pytest.raises(ValueError, match='outside'):
        tool_registry(store, ontology, old)['get_exact_source'].invoke({'anchor_id': anchor})


@pytest.mark.asyncio
async def test_invalid_source_tool_argument_is_reported_and_agent_can_recover(store, ontology):
    publish_fixture(store, ontology)
    store.config.text_provider = 'compatible'
    store.config.text_model = store.config.verifier_model = 'fixture-model'
    class RecoveringPlanner(Planner):
        async def choose_tools(self, messages, tools, budget):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='', tool_calls=[{'id': 'search-1', 'name': 'search_precedents',
                    'args': {'query': 'planter membrane repair'}, 'type': 'tool_call'}])
            if self.calls == 2:
                return AIMessage(content='', tool_calls=[{'id': 'wrong-source', 'name': 'get_exact_source',
                    'args': {'anchor_id': 'anchor_invented_from_a_chunk_id'}, 'type': 'tool_call'}])
            feedback = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert feedback['error']['kind'] == 'invalid_tool_arguments'
            assert feedback['valid_anchor_ids']
            return AIMessage(content='', tool_calls=[{'id': 'correct-source', 'name': 'get_exact_source',
                'args': {'anchor_id': feedback['valid_anchor_ids'][0]}, 'type': 'tool_call'}])
    rid = run_record(store)
    async with checkpoint_session(store) as saver:
        await execute_research(store, build_research(store, saver, ontology, Synthesis(store), Verifier(), RecoveringPlanner()), rid)
    run = store.require('SELECT * FROM runs WHERE id=?', (rid,))
    assert run['error'] is None and json.loads(run['answer'])['claims']
    bundle = json.loads(run['evidence'])
    assert bundle['sources'] and 'anchor_invented_from_a_chunk_id' not in bundle['sources']
    assert len(store.all("SELECT sequence FROM events WHERE owner_id=? AND type='tool_failed'", (rid,))) == 1
    errors = [json.loads(op['result']) for op in store.all("SELECT result FROM operations WHERE owner_id=? AND node='tool:get_exact_source'", (rid,))]
    assert any(e.get('error') for e in errors) and any(e.get('quote') for e in errors)


@pytest.mark.asyncio
async def test_unexpected_source_service_failure_stops_without_fabricating_evidence(store, ontology, monkeypatch):
    publish_fixture(store, ontology)
    store.config.text_provider = 'compatible'
    store.config.text_model = store.config.verifier_model = 'fixture-model'
    def unavailable(*args):
        raise RuntimeError('canonical source service unavailable')
    monkeypatch.setattr('app.research_tools.source', unavailable)
    rid = run_record(store)
    async with checkpoint_session(store) as saver:
        await execute_research(store, build_research(store, saver, ontology, Synthesis(store), Verifier(), Planner()), rid)
    run = store.require('SELECT * FROM runs WHERE id=?', (rid,))
    assert run['status'] == 'interrupted' and 'source service unavailable' in run['error']
    assert not json.loads(run['answer']).get('claims')
    assert json.loads(run['evidence'])['items']
    assert not store.all("SELECT sequence FROM events WHERE owner_id=? AND type='tool_failed'", (rid,))


@pytest.mark.asyncio
async def test_unknown_model_outcome_is_not_automatically_retried(store, ontology):
    publish_fixture(store, ontology)
    store.config.text_provider = 'compatible'
    store.config.text_model = 'fixture-model'
    class Failure(Planner):
        async def choose_tools(self, messages, tools, budget):
            self.calls += 1
            raise TimeoutError('provider timed out')
    planner = Failure()
    rid = run_record(store)
    async with checkpoint_session(store) as saver:
        graph = build_research(store, saver, ontology, planner=planner)
        await execute_research(store, graph, rid)
        store.config.text_model = 'changed-after-timeout'
        await execute_research(store, graph, rid)
    assert planner.calls == 1
    assert 'outcome unknown' in store.require('SELECT error FROM runs WHERE id=?', (rid,))['error']


@pytest.mark.asyncio
async def test_drafting_timeout_is_not_replayed_after_model_or_prompt_changes(store, ontology):
    publish_fixture(store, ontology)
    store.config.text_provider = 'compatible'
    store.config.text_model = store.config.verifier_model = 'fixture-model'
    class TimeoutSynthesis(Synthesis):
        calls = 0

        async def generate_structured(self, schema, messages, budget):
            self.calls += 1
            raise TimeoutError('provider timed out')
    port = TimeoutSynthesis(store)
    rid = run_record(store)
    async with checkpoint_session(store) as saver:
        graph = build_research(store, saver, ontology, port, Verifier(), Planner())
        await execute_research(store, graph, rid)
        assert store.require('SELECT status FROM runs WHERE id=?', (rid,))['status'] == 'interrupted'
        assert json.loads(store.require('SELECT evidence FROM runs WHERE id=?', (rid,))['evidence'])['items']
        store.config.text_model = 'changed-after-timeout'
        await execute_research(store, graph, rid)
    assert port.calls == 1
    assert 'outcome unknown' in store.require('SELECT error FROM runs WHERE id=?', (rid,))['error']


def test_named_credentials_and_official_endpoint_enforcement():
    config = Settings(_env_file=None, openai_api_key='fixture-openai', fireworks_api_key='fixture-fireworks', text_model='fixture-model')
    assert text_credential(config, 'openai') == 'fixture-openai'
    assert text_credential(config, 'fireworks') == 'fixture-fireworks'
    config.text_provider = 'openai'
    config.text_endpoint = 'https://unrelated.invalid/v1'
    with pytest.raises(ValueError, match='official'):
        language_model(config)


def test_saved_provider_selection_applies_without_persisting_secrets(store):
    from app.store import canonical
    store.config.fireworks_api_key = 'fixture-fireworks'
    store.insert('workspace', {'key': 'settings', 'value': canonical({
        'version': 2, 'text_provider': 'fireworks', 'text_endpoint': 'https://api.fireworks.ai/inference/v1',
        'text_model': 'fixture-model', 'verifier_model': 'fixture-verifier', 'model_timeout':137, 'provider_key': 'must-not-load'})})
    apply_saved_text_settings(store)
    assert store.config.text_provider == 'fireworks' and store.config.text_model == 'fixture-model'
    assert text_credential(store.config) == 'fixture-fireworks'
    assert not store.config.provider_key
    assert store.config.model_timeout == 137
