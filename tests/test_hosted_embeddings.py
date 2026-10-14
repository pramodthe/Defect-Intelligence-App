import json
import math
from contextlib import closing

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from qdrant_client import QdrantClient

from app.embeddings import HostedEmbedding, embedding_spec, public_settings
from app.embedding_index import queue_reindex, rebuild, save_settings
from app.main import create_app
from app.projections import QdrantProjection
from app.retrieval import search
from tests.conftest import publish_fixture, synthetic_docx
from app.store import canonical


def configure(store, provider="openai", model="", dimensions=3):
    store.config.embedding_provider = provider
    store.config.embedding_model = model
    store.config.embedding_dimensions = dimensions
    store.config.openai_api_key = "synthetic-openai-key"
    store.config.fireworks_api_key = "synthetic-fireworks-key"


def recording_client(store, requests, respond=None):
    spec = embedding_spec(store.config)

    def transport(request):
        payload = json.loads(request.content)
        requests.append((str(request.url), dict(request.headers), payload))
        if respond:
            return respond(payload)
        data = [{"index": i, "object": "embedding", "embedding": [3., 4., 0.]}
                for i in reversed(range(len(payload["input"])))]
        return httpx.Response(200, json={"object": "list", "model": spec.model, "data": data,
                                         "usage": {"prompt_tokens": 2, "total_tokens": 2}})

    return OpenAI(api_key="synthetic-client-key", base_url=spec.endpoint, max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(transport)))


@pytest.mark.parametrize("provider,model,expected", [
    ("openai", "text-embedding-3-small", 1536),
    ("openai", "text-embedding-3-large", 3072),
    ("fireworks", "accounts/fireworks/models/qwen3-embedding-8b", 4096),
])
def test_profiles_have_provider_specific_dimensions_and_do_not_share_indexes(store, provider, model, expected):
    configure(store, provider, model, 0)
    spec = embedding_spec(store.config)
    assert spec.dimensions == expected
    original = spec.profile
    store.config.embedding_dimensions = 256
    assert embedding_spec(store.config).profile != original
    assert "synthetic" not in spec.profile


@pytest.mark.parametrize("provider", ["openai", "fireworks"])
def test_actual_sdk_request_contract_reordered_results_normalization_and_cache(store, provider):
    configure(store, provider)
    requests = []
    with recording_client(store, requests) as client:
        embedder = HostedEmbedding(store, client)
        query = embedder.query_text("planter membrane")
        if provider == "openai":
            assert query == "planter membrane"
        else:
            assert query.startswith("Instruct: ")
        vectors = embedder.encode(["first passage", "second passage"])
        assert len(vectors) == 2 and vectors[0] == pytest.approx([.6, .8, 0])
        assert all(math.isclose(math.hypot(*v), 1) for v in vectors)
        assert requests[0][0] == embedder.spec.endpoint + "/embeddings"
        assert requests[0][2]["dimensions"] == 3
        assert requests[0][2]["encoding_format"] == "float"
        assert set(requests[0][2]) == {"model", "input", "dimensions", "encoding_format"}
        assert embedder.encode(["first passage", "second passage"]) == vectors
        assert len(requests) == 1
        assert store.require("SELECT state FROM operations")["state"] == "complete"


@pytest.mark.parametrize("data", [
    [{"index": 0, "embedding": [1., 0.]}],
    [{"index": 0, "embedding": [0., 0., 0.]}],
    [{"index": 1, "embedding": [1., 0., 0.]}],
    [{"index": 0, "embedding": [1., 0., 0.]}, {"index": 0, "embedding": [1., 0., 0.]}],
])
def test_malformed_embeddings_never_publish_or_silently_retry(store, data):
    configure(store)
    requests = []
    with recording_client(store, requests, lambda p: httpx.Response(200, json={
        "object": "list", "model": "text-embedding-3-small", "data": data,
        "usage": {"prompt_tokens": 1, "total_tokens": 1}})) as client:
        embedder = HostedEmbedding(store, client)
        with pytest.raises(RuntimeError, match="no automatic retry"):
            embedder.encode(["private synthetic passage"])
        with pytest.raises(RuntimeError, match="unknown outcome"):
            embedder.encode(["private synthetic passage"])
        assert len(requests) == 1


def test_provider_failure_masks_secret_body_and_retains_charged_attempt(store):
    configure(store)
    requests = []
    with recording_client(store, requests, lambda p: httpx.Response(429, json={
        "error": {"message": "private synthetic passage synthetic-openai-key", "type": "rate_limit"}})) as client:
        with pytest.raises(RuntimeError) as error:
            HostedEmbedding(store, client).encode(["private synthetic passage"])
        assert "private synthetic" not in str(error.value) and "synthetic-openai-key" not in str(error.value)
        assert len(requests) == 1
        assert store.require("SELECT seconds FROM budgets")["seconds"] > 0


def test_missing_key_and_model_validation_never_send_content(store):
    configure(store)
    store.config.openai_api_key = ""
    with pytest.raises(ValueError, match="API key"):
        HostedEmbedding(store).encode(["synthetic passage"])
    store.config.embedding_model = "not-an-embedding-model"
    with pytest.raises(ValueError):
        embedding_spec(store.config)
    assert not store.all("SELECT * FROM operations")


def test_embedding_settings_persist_with_no_secret_in_api_response(store):
    configure(store)
    api = create_app(store.config)
    client = TestClient(api)
    payload = {"expected_version": 1, "embedding_provider": "fireworks", "embedding_model": "", "embedding_dimensions": 256}
    response = client.put("/api/embedding-settings", json=payload, headers={"X-Workspace-Request": "1"})
    assert response.status_code == 200
    assert response.json()["embedding_dimensions"] == 256
    assert "synthetic-openai-key" not in response.text and "synthetic-fireworks-key" not in response.text
    assert client.put("/api/embedding-settings", json=payload, headers={"X-Workspace-Request": "1"}).status_code == 400
    restarted = TestClient(create_app(store.config))
    assert restarted.get("/api/embedding-settings").json()["embedding_provider"] == "fireworks"


def test_reindex_validates_new_dimensions_and_publishes_all_documents_atomically(store, ontology, monkeypatch):
    first = publish_fixture(store, ontology)
    second = publish_fixture(store, ontology, synthetic_docx(count=4))
    before = store.active_manifest()
    configure(store)
    store.config.qdrant_url = "test-local-qdrant"
    requests = []
    with recording_client(store, requests) as client:
        monkeypatch.setattr("app.projections.embedding_provider", lambda s, owner=None: HostedEmbedding(s, client, owner))
        monkeypatch.setattr(QdrantProjection, "client", lambda self: QdrantClient(path=str(store.root / "isolated-qdrant")))
        queued = queue_reindex(store)
        assert store.active_manifest() == before
        result = rebuild(store, ontology, store.require("SELECT * FROM outbox WHERE id=?", (queued['id'],)))
        assert result['manifest_id'] != before
        assert public_settings(store)['index_state'] == 'ready'
        assert store.require("SELECT state FROM outbox WHERE id=?", (queued['id'],))['state'] == 'complete'
        assert {m['document_id'] for m in store.all("SELECT * FROM manifest_members WHERE manifest_id=?", (result['manifest_id'],))} == {first['document_id'], second['document_id']}
        assert any('semantic' in r['retrieval_methods'] for r in search(store, ontology, 'planter')['items'])
        with closing(QdrantClient(path=str(store.root / "isolated-qdrant"))) as qdrant:
            assert all(qdrant.get_collection(c.name).config.params.vectors.size == 3 for c in qdrant.get_collections().collections)


def test_provider_switch_never_queries_vectors_from_another_profile(store, ontology, monkeypatch):
    publish_fixture(store, ontology)
    configure(store)
    store.config.qdrant_url = "test"
    monkeypatch.setattr(QdrantProjection, "search", lambda *a, **k: pytest.fail("Wrong-profile vectors were queried"))
    result = search(store, ontology, 'planter')
    assert result['items'] and any('rebuild' in warning for warning in result['warnings'])
    assert public_settings(store)['index_state'] == 'rebuild_required'


def test_failed_rebuild_and_concurrent_source_change_cannot_replace_library(store, ontology, monkeypatch):
    publish_fixture(store, ontology)
    before = store.active_manifest()
    configure(store)
    store.config.qdrant_url = "test"
    queued = queue_reindex(store)
    event = store.require("SELECT * FROM outbox WHERE id=?", (queued['id'],))
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic unavailable provider")
    monkeypatch.setattr("app.embedding_index.stage", fail)
    with pytest.raises(RuntimeError):
        rebuild(store, ontology, event)
    assert store.active_manifest() == before
    with pytest.raises(ValueError, match='current index rebuild'):
        save_settings(store, {"expected_version": 1, "embedding_provider": "openai", "embedding_model": "", "embedding_dimensions": 3})
    with pytest.raises(ValueError, match='Source library changed'):
        store.activate_reindex({}, 'different-manifest', {})


def test_rebuild_progress_preserves_renewed_worker_lease(store, ontology, monkeypatch):
    publish_fixture(store, ontology)
    publish_fixture(store, ontology, synthetic_docx(count=4))
    configure(store)
    store.config.qdrant_url = "test"
    queued = queue_reindex(store)
    event = store.require("SELECT * FROM outbox WHERE id=?", (queued['id'],))
    payload = json.loads(event['payload'])
    payload['lease_until'] = 100
    event['payload'] = canonical(payload)
    store.execute("UPDATE outbox SET state='running',payload=? WHERE id=?", (event['payload'], queued['id']))
    calls = []
    def stage_with_lease(s, document_id, *args, **kwargs):
        if calls:
            assert json.loads(s.require("SELECT payload FROM outbox WHERE id=?", (queued['id'],))['payload'])['lease_until'] == 200
        s.execute("UPDATE outbox SET payload=json_set(payload,'$.lease_until',200) WHERE id=?", (queued['id'],))
        calls.append(document_id)
        old = s.require("SELECT projection_id FROM manifest_members WHERE manifest_id=? AND document_id=?", (s.active_manifest(), document_id))
        return {"projection_id": old['projection_id'], "receipts": {"vectors": {"state": "ready"}}}
    monkeypatch.setattr('app.embedding_index.stage', stage_with_lease)
    rebuild(store, ontology, event)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_worker_reindex_wrapper_reads_claimed_event_and_cleans_up_heartbeat(store, ontology, monkeypatch):
    from app.worker import process_reindex
    store.insert('outbox', {'id':'job_embedding_test', 'kind':'embedding_reindex', 'payload':{'lease_until':200}, 'state':'running'})
    captured = []
    def fake_rebuild(s, o, event):
        captured.append(json.loads(event['payload']))
        return {'manifest_id':'synthetic-manifest'}
    monkeypatch.setattr('app.worker.rebuild', fake_rebuild)
    assert await process_reindex(store, ontology, 'job_embedding_test') == {'manifest_id':'synthetic-manifest'}
    assert captured == [{'lease_until':200}]
