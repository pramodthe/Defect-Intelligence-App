import copy
import json

import pytest

from app.providers import language_model
from app.research_evidence import evidence_pack
from app.research_tools import model_view
from app.retrieval import search, source
from app.settings import Settings
from app.store import canonical
from tests.conftest import publish_fixture


def test_compact_context_preserves_quotes_scope_alternatives_and_canonical_data(store, ontology):
    publish_fixture(store, ontology)
    items = search(store, ontology, 'planter membrane reasoning repair')['items']
    # Duplicated search/graph hits must not repeat original paragraph text.
    duplicated = [*items, copy.deepcopy(items[0])]
    before = canonical(duplicated)
    pack = evidence_pack(store, duplicated, 'planter membrane reasoning repair')
    assert canonical(duplicated) == before
    assert len(pack.payload['sources']) == len(pack.citations)
    assert pack.receipt['omitted_passages'] == 0
    purposes = {e['metadata']['section_purpose'] for e in pack.payload['evidence']}
    assert {'reasoning', 'remediation'} <= purposes
    for passage in pack.payload['sources']:
        original = source(store, pack.citations[passage['id']])
        assert passage['quote'] == original['quote']
        if original['text'] != original['quote']:
            assert passage['block_context'] == original['text']
    label = pack.payload['sources'][0]['id']
    claims = [{'anchor_ids': [label, 'fabricated'], 'text': 'test'}]
    canonical_claims = pack.canonical_claims(claims)
    assert canonical_claims[0]['anchor_ids'] == [pack.citations[label], 'fabricated']
    assert pack.model_claims(canonical_claims) == claims
    assert 'source_segments' not in canonical(pack.payload)
    assert len(canonical(pack.payload)) < len(canonical(duplicated))


def test_context_limit_excludes_whole_chunks_and_reports_coverage(store, ontology):
    publish_fixture(store, ontology)
    items = search(store, ontology, 'planter membrane reasoning repair')['items']
    pack = evidence_pack(store, items, 'planter membrane reasoning repair', max_chars=2300)
    assert pack.receipt['context_chars'] <= 2300
    assert pack.receipt['omitted_passages'] > 0 and pack.gaps
    assert pack.payload['coverage']['gaps'] == pack.gaps
    for passage in pack.payload['sources']:
        assert passage['quote'] == source(store, pack.citations[passage['id']])['quote']
    # A very large paragraph cannot silently become a short quotation.
    empty = evidence_pack(store, items, 'planter', max_chars=1000)
    assert not empty.payload['sources'] and empty.gaps


def test_tool_model_view_keeps_required_tool_ids_without_internal_projection_metadata(store, ontology):
    publish_fixture(store, ontology)
    result = search(store, ontology, 'planter repair')
    before = copy.deepcopy(result)
    compact = model_view('search_precedents', result)
    assert result == before
    assert compact['items'][0]['id'] == result['items'][0]['id']
    assert compact['items'][0]['anchor_ids'] == result['items'][0]['anchor_ids']
    assert compact['items'][0]['metadata']['defect_item_id'] == result['items'][0]['metadata']['defect_item_id']
    assert 'source_segments' not in compact['items'][0]['metadata']
    anchor = source(store, result['items'][0]['anchor_ids'][0])
    assert model_view('get_exact_source', anchor)['quote'] == anchor['quote']


@pytest.mark.parametrize('provider,model,endpoint,expected', [
    ('fireworks', 'accounts/fireworks/models/qwen3p8-max', 'https://api.fireworks.ai/inference/v1', {'reasoning_effort': 1024}),
    ('fireworks', 'another-model', 'https://api.fireworks.ai/inference/v1', None),
    ('openai', 'gpt-4.1', 'https://api.openai.com/v1', None),
    ('compatible', 'qwen3p8-max', 'https://example.invalid/v1', None),
])
def test_reasoning_cap_is_a_fireworks_qwen_extension_only(provider, model, endpoint, expected):
    config = Settings(_env_file=None, text_provider=provider, text_model=model, text_endpoint=endpoint,
                      openai_api_key='fixture', fireworks_api_key='fixture', provider_key='fixture')
    chat = language_model(config)
    payload = chat._get_request_payload([{'role': 'user', 'content': 'test'}])
    assert payload.get('extra_body') == expected
    assert chat.max_retries == 0
    assert 'fixture' not in json.dumps(payload)
