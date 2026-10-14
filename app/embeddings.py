"""Explicit text embedding destinations; originals and image pixels are never inputs."""
import json
import math
import time
from dataclasses import dataclass
from typing import Any

from app.settings import Settings
from app.store import Store, canonical, digest, identity


OPENAI_MODELS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}
FIREWORKS_MODEL = "accounts/fireworks/models/qwen3-embedding-8b"
OPTIONS = [
    {"provider": "local_bge", "label": "Local BGE", "model": "BAAI/bge-base-en-v1.5", "dimensions": 768},
    *[{"provider": "openai", "label": "OpenAI", "model": model, "dimensions": size}
      for model, size in OPENAI_MODELS.items()],
    {"provider": "fireworks", "label": "Fireworks · Qwen3 Embedding 8B", "model": FIREWORKS_MODEL,
     "dimensions": 4096},
]
QUERY_TASK = "Given a building defect research query, retrieve relevant report passages"


def selected_config(store: Store) -> Settings:
    row = store.one("SELECT value FROM workspace WHERE key='embedding_settings'")
    overrides = json.loads(row["value"]) if row else {}
    return store.config.model_copy(update={key: overrides[key] for key in
        ("embedding_provider", "embedding_model", "embedding_dimensions") if key in overrides})


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model: str
    dimensions: int
    endpoint: str
    profile: str


def embedding_spec(config: Settings) -> EmbeddingSpec:
    provider = config.embedding_provider
    model = config.embedding_model
    dimensions = config.embedding_dimensions
    if provider == "local_bge":
        from pathlib import Path
        if model not in {"", "BAAI/bge-base-en-v1.5"} or dimensions not in {0, 768}:
            raise ValueError("Local BGE requires its frozen model and 768 dimensions")
        return EmbeddingSpec(provider, "BAAI/bge-base-en-v1.5", 768, "local",
                             "bge-base-en-v1.5/" + Path(config.embedding_path).name)
    if provider == "disabled":
        return EmbeddingSpec(provider, "", 0, "", "disabled")
    if provider == "openai":
        model = model or "text-embedding-3-small"
        if model not in OPENAI_MODELS:
            raise ValueError("Choose text-embedding-3-small or text-embedding-3-large")
        maximum = OPENAI_MODELS[model]
        endpoint = "https://api.openai.com/v1"
    elif provider == "fireworks":
        model = model or FIREWORKS_MODEL
        if model == "fireworks/qwen3-embedding-8b":
            model = FIREWORKS_MODEL
        if model != FIREWORKS_MODEL:
            raise ValueError("This Fireworks profile supports Qwen3 Embedding 8B")
        maximum = 4096
        endpoint = "https://api.fireworks.ai/inference/v1"
    else:
        raise ValueError("Unknown embedding provider")
    dimensions = dimensions or maximum
    if not 1 <= dimensions <= maximum:
        raise ValueError(f"Embedding dimension must be between 1 and {maximum}")
    profile = "hosted-text/1/" + digest([provider, endpoint, model, dimensions,
        QUERY_TASK if provider == "fireworks" else "plain-query", "l2"])
    return EmbeddingSpec(provider, model, dimensions, endpoint, profile)


def credential(config: Settings, spec: EmbeddingSpec) -> str:
    return config.openai_api_key if spec.provider == "openai" else config.fireworks_api_key


def configured(store: Store) -> bool:
    config = selected_config(store)
    spec = embedding_spec(config)
    return bool(config.embedding_path) if spec.provider == "local_bge" else (
        spec.provider != "disabled" and bool(credential(config, spec)))


def public_settings(store: Store) -> dict:
    config = selected_config(store)
    spec = embedding_spec(config)
    row = store.one("SELECT value FROM workspace WHERE key='embedding_settings'")
    ready = configured(store)
    projections = store.all("SELECT p.receipts FROM manifest_members m JOIN projections p ON p.id=m.projection_id WHERE m.manifest_id=?",
                            (store.active_manifest(),))
    matching = [json.loads(p["receipts"]).get("vectors", {}).get("profile") == spec.profile for p in projections]
    event = store.one("SELECT id,state,payload FROM outbox WHERE kind='embedding_reindex' ORDER BY rowid DESC LIMIT 1")
    last_job = None
    if event:
        payload = json.loads(event["payload"])
        last_job = {"id": event["id"], "status": event["state"], "completed_documents": payload.get("completed_documents", 0),
                    "total_documents": len(payload["documents"]), "error": payload.get("error", "")}
    return {"version": json.loads(row["value"])["version"] if row else 1,
        "embedding_provider": spec.provider, "embedding_model": spec.model,
        "embedding_dimensions": spec.dimensions, "endpoint": spec.endpoint,
        "credential_configured": ready, "profile": spec.profile, "options": OPTIONS,
        "credentials": {"openai": bool(config.openai_api_key), "fireworks": bool(config.fireworks_api_key),
                        "local_bge": bool(config.embedding_path), "disabled": False},
        "index_state": "disabled" if spec.provider == 'disabled' else "empty" if not matching else "ready" if all(matching) else "rebuild_required",
        "indexed_documents": sum(matching), "total_documents": len(matching), "last_job": last_job,
        "modality": "text", "visual_retrieval": "Image embeddings have separate provider, permission and capability settings",
        "transmission": "Local text processing" if spec.provider == "local_bge" else
            "Disabled" if spec.provider == "disabled" else "Report chunks and search queries sent to the selected provider; no originals or pixels"}


def normalized(vector: Any, dimensions: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise ValueError("Embedding response dimension mismatch")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
        raise ValueError("Embedding response contains invalid values")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("Embedding response has zero or invalid norm")
    return [float(value / norm) for value in vector]


class HostedEmbedding:
    def __init__(self, store: Store, client=None, owner: str | None = None):
        self.store = store
        self.config = selected_config(store)
        self.spec = embedding_spec(self.config)
        self.profile = self.spec.profile
        self.dimensions = self.spec.dimensions
        self.client = client
        self.owner = owner

    def query_text(self, question: str) -> str:
        return f"Instruct: {QUERY_TASK}\nQuery: {question}" if self.spec.provider == "fireworks" else question

    def encode(self, texts: list[str]) -> list[list[float]]:
        if self.spec.provider not in {"openai", "fireworks"} or not credential(self.config, self.spec):
            raise ValueError("Configure the selected embedding provider's server-side API key")
        # UTF-8 byte length is a conservative token upper bound; never silently truncate.
        if any(not isinstance(t, str) or not t.strip() or len(t.encode("utf-8")) > 8191 for t in texts):
            raise ValueError("Hosted embedding input must be nonempty text within the 8191-byte safety limit")
        if not texts:
            return []
        cache = self.store.root / "derived/embeddings" / digest(self.profile)[:16]
        cache.mkdir(parents=True, exist_ok=True)
        vectors: list[Any] = [None] * len(texts)
        missing = []
        for index, text in enumerate(texts):
            path = cache / (digest(text) + ".json")
            if path.exists():
                try:
                    vectors[index] = normalized(json.loads(path.read_text(encoding="utf-8")), self.dimensions)
                    continue
                except (ValueError, TypeError):
                    pass
            missing.append(index)
        for start in range(0, len(missing), 32):
            indexes = missing[start:start + 32]
            inputs = [texts[i] for i in indexes]
            hashes = [digest(t) for t in inputs]
            owner = self.owner or identity("embedding", self.profile, hashes)
            prior_id = identity("operation", owner, "hosted_embedding", {"profile": self.profile, "input_hashes": hashes})
            prior = self.store.one("SELECT * FROM operations WHERE id=?", (prior_id,))
            if prior and prior["state"] != "complete":
                raise RuntimeError("Previous embedding attempt has unknown outcome; inspect it before an explicit retry")
            op = self.store.reserve(owner, "hosted_embedding", {"profile": self.profile, "input_hashes": hashes},
                                    tools=1, allowance=self.config.embedding_timeout)
            if op["state"] == "complete":
                batch = json.loads(op["result"])["vectors"]
            else:
                from openai import OpenAI
                client = self.client or OpenAI(api_key=credential(self.config, self.spec), base_url=self.spec.endpoint,
                                              timeout=self.config.embedding_timeout, max_retries=0)
                try:
                    response = client.embeddings.create(model=self.spec.model, input=inputs,
                        dimensions=self.dimensions, encoding_format="float")
                    rows = {row.index: row.embedding for row in response.data}
                    if len(response.data) != len(inputs) or set(rows) != set(range(len(inputs))):
                        raise ValueError("Embedding response indexes/count do not match the input")
                    batch = [normalized(rows[i], self.dimensions) for i in range(len(inputs))]
                    self.store.complete_operation(op, {"vectors": batch, "profile": self.profile})
                except Exception as exc:
                    # Do not expose provider error bodies, request content or credentials.
                    raise RuntimeError(f"Hosted embedding request failed ({type(exc).__name__}); no automatic retry") from None
                finally:
                    if self.client is None:
                        client.close()
            for index, vector in zip(indexes, batch, strict=True):
                vectors[index] = normalized(vector, self.dimensions)
                path = cache / (digest(texts[index]) + ".json")
                temporary = cache / (digest([texts[index], time.time_ns()]) + ".tmp")
                temporary.write_text(canonical(vectors[index]), encoding="utf-8")
                temporary.replace(path)
        return vectors


def embedding_provider(store: Store, owner: str | None = None):
    config = selected_config(store)
    spec = embedding_spec(config)
    if spec.provider == "local_bge":
        from app.projections import LocalEmbedding
        return LocalEmbedding(store)
    if spec.provider == "disabled":
        raise ValueError("Embedding provider disabled")
    return HostedEmbedding(store, owner=owner)
