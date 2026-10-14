"""Versioned Voyage image retrieval, independent of text embeddings and vision chat."""
import base64
import io
import json
import re
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageOps

from app.embeddings import normalized
from app.settings import Settings
from app.store import Store, canonical, digest, identity, new_id

FIELDS = ("visual_embedding_provider", "visual_embedding_deployment", "visual_embedding_dimensions", "visual_embedding_enabled")
MODEL = "voyage-multimodal-3.5"
DIMENSIONS = (256, 512, 1024, 2048)
PREPROCESS = "rgb-png-long-edge-1600/1"
MAX_IMAGE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class VisualSpec:
    provider: str
    model: str
    endpoint: str
    dimensions: int
    profile: str


def selected_config(store: Store) -> Settings:
    row = store.one("SELECT value FROM workspace WHERE key='visual_embedding_settings'")
    values = json.loads(row["value"]) if row else {}
    return store.config.model_copy(update={key: values[key] for key in FIELDS if key in values})


def spec(config: Settings) -> VisualSpec:
    provider = config.visual_embedding_provider
    if config.visual_embedding_dimensions not in DIMENSIONS:
        raise ValueError("Voyage dimensions must be 256, 512, 1024 or 2048")
    if provider == "disabled":
        return VisualSpec(provider, "", "", config.visual_embedding_dimensions, "disabled")
    if provider not in {"fireworks_voyage", "voyage"}:
        raise ValueError("Choose Fireworks Voyage, Voyage direct, or disabled")
    if provider == "fireworks_voyage":
        model = config.visual_embedding_deployment.strip()
        if model and not re.fullmatch(r"accounts/[A-Za-z0-9_-]+/deployments/[A-Za-z0-9_-]+", model):
            raise ValueError("Use a Fireworks deployment path: accounts/your-account/deployments/your-deployment")
        endpoint = "https://api.fireworks.ai/inference/v1/embeddings"
        wire_format = "fireworks-content/1"
    else:
        model = MODEL
        endpoint = "https://api.voyageai.com/v1/multimodalembeddings"
        wire_format = "voyage-native/1"
    profile = "visual-voyage/1/" + digest([provider, model, endpoint, config.visual_embedding_dimensions,
        wire_format, PREPROCESS, "document-query-input-types", "l2"])
    return VisualSpec(provider, model, endpoint, config.visual_embedding_dimensions, profile)


def key(config: Settings, profile: VisualSpec) -> str:
    return config.fireworks_api_key if profile.provider == "fireworks_voyage" else config.voyage_api_key


def capability_key(profile: VisualSpec) -> str:
    return "visual_capability_" + digest(profile.profile)[:24]


def capable(store: Store, profile: VisualSpec | None = None) -> bool:
    profile = profile or spec(selected_config(store))
    row = store.one("SELECT value FROM workspace WHERE key=?", (capability_key(profile),))
    return bool(row and json.loads(row["value"]).get("state") == "verified")


def configured(store: Store) -> bool:
    config = selected_config(store)
    profile = spec(config)
    return (profile.provider != "disabled" and config.visual_embedding_enabled and bool(profile.model)
            and bool(key(config, profile)) and capable(store, profile))


def public_settings(store: Store) -> dict:
    config = selected_config(store)
    profile = spec(config)
    saved = store.one("SELECT value FROM workspace WHERE key='visual_embedding_settings'")
    verified = capable(store, profile)
    members = store.all("SELECT m.document_id,p.receipts FROM manifest_members m JOIN projections p ON p.id=m.projection_id WHERE m.manifest_id=?", (store.active_manifest(),))
    total = sum(store.require("SELECT COUNT(*) n FROM media WHERE document_id=?", (m['document_id'],))['n'] for m in members)
    matching = [json.loads(m['receipts']).get('visuals', {}) for m in members]
    matching = [r for r in matching if r.get('profile') == profile.profile and r.get('state') == 'ready']
    indexed = sum(r.get('count', 0) for r in matching)
    skipped = sum(len(r.get('skipped', [])) for r in matching)
    state = 'disabled' if not config.visual_embedding_enabled or profile.provider == 'disabled' else (
        'empty' if not total else 'ready' if len(matching) == len(members) and not skipped else
        'partial' if len(matching) == len(members) else 'rebuild_required')
    return {"version": json.loads(saved['value'])['version'] if saved else 1,
        **{field: getattr(config, field) for field in FIELDS}, "model": MODEL, "endpoint": profile.endpoint,
        "profile": profile.profile, "capability_verified": verified, "credential_configured": bool(key(config, profile)),
        "credentials": {"fireworks_voyage": bool(config.fireworks_api_key), "voyage": bool(config.voyage_api_key)},
        "configured": configured(store), "index_state": state, "indexed_media": indexed, "total_media": total,
        "skipped_media": skipped, "dimensions": list(DIMENSIONS),
        "fireworks_format": "OpenAI-compatible content adapter; deployed image support must pass the synthetic test",
        "transmission": "Embedded report images plus bounded captions/OCR and text queries; no original Word/PDF uploads",
        "preprocessing": PREPROCESS}


def save_settings(store: Store, payload: dict) -> dict:
    config = store.config.model_copy(update={field: payload[field] for field in FIELDS})
    profile = spec(config)
    if profile.provider == 'disabled' and config.visual_embedding_enabled:
        raise ValueError("Select a visual provider before enabling image transmission")
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute("SELECT value FROM workspace WHERE key='maintenance' AND value='1'").fetchone():
            raise ValueError('Wait for workspace recovery')
        if con.execute("SELECT id FROM outbox WHERE kind='embedding_reindex' AND state IN ('pending','running')").fetchone():
            raise ValueError('Wait for the current rebuild before changing visual settings')
        current = con.execute("SELECT value FROM workspace WHERE key='visual_embedding_settings'").fetchone()
        version = json.loads(current[0])['version'] if current else 1
        if version != payload['expected_version']:
            raise ValueError('Stale visual settings; reload before saving')
        record = {'version': version + 1, **{field: payload[field] for field in FIELDS}}
        con.execute("INSERT INTO workspace(key,value) VALUES('visual_embedding_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (canonical(record),))
    return {'status': 'Visual embedding settings saved. Test the connection, then rebuild the index.', **public_settings(store)}


def pixels(data: bytes, max_pixels=40_000_000) -> bytes:
    """Create a bounded retrieval derivative in memory; original assets are never rewritten."""
    if len(data) > 50 * 1024 * 1024:
        raise ValueError("image_too_large")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP", "GIF", "TIFF", "BMP"}:
                raise ValueError("unsupported_image_format")
            if source.width * source.height > max_pixels:
                raise ValueError("image_pixel_limit")
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1600, 1600))
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            image = Image.alpha_composite(background, image).convert("RGB")
            output = io.BytesIO()
            image.save(output, "PNG")
            result = output.getvalue()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("unsupported_or_invalid_image") from exc
    if len(result) > MAX_IMAGE_BYTES:
        raise ValueError("image_payload_limit")
    return result


def content(text: str = "", image: bytes | None = None) -> dict:
    if len(text.encode("utf-8")) > 8191:
        raise ValueError("Visual embedding context exceeds the text safety limit")
    parts: list[dict] = []
    if text.strip():
        parts.append({"type": "text", "text": text})
    if image is not None:
        if len(image) > MAX_IMAGE_BYTES:
            raise ValueError("image_payload_limit")
        parts.append({"type": "image_base64", "image_base64": "data:image/png;base64," + base64.b64encode(image).decode("ascii")})
    if not parts:
        raise ValueError("Visual embedding input cannot be empty")
    return {"content": parts}


class VoyageVisualEmbedding:
    def __init__(self, store: Store, owner=None, client: httpx.Client | None = None):
        self.store = store
        self.config = selected_config(store)
        self.spec = spec(self.config)
        self.profile = self.spec.profile
        self.dimensions = self.spec.dimensions
        self.owner = owner
        self.client = client

    def request_body(self, inputs: list[dict], input_type: str) -> dict:
        if self.spec.provider == "voyage":
            body: dict[str, Any] = {"model": self.spec.model, "inputs": inputs, "input_type": input_type,
                                    "truncation": False}
            if self.dimensions != 1024:
                body["output_dimension"] = self.dimensions
            return body
        # Fireworks' documented OpenAI-compatible endpoint has no published image example.
        # This declared content format must pass the synthetic cross-modal test before any source pixels.
        converted = []
        for entry in inputs:
            converted.append({"content": [
                {"type": "image_url", "image_url": {"url": part["image_base64"]}}
                if part["type"] == "image_base64" else part for part in entry["content"]]})
        body = {"model": self.spec.model, "input": converted, "input_type": input_type, "encoding_format": "float"}
        if self.dimensions != 1024:
            body["dimensions"] = self.dimensions
        return body

    def encode(self, inputs: list[dict], input_type="document", probe=False) -> list[list[float]]:
        if input_type not in {"document", "query"}:
            raise ValueError("Specify document or query embedding inputs")
        if self.spec.provider == "disabled" or not self.spec.model or not key(self.config, self.spec):
            raise ValueError("Configure the visual embedding API key and deployment first")
        if not probe and not configured(self.store):
            raise ValueError("Enable image embeddings and pass the synthetic image test before transmitting source pixels")
        if not inputs:
            return []
        if len(inputs) > 8:
            raise ValueError("Visual embedding requests are limited to eight inputs")
        for entry in inputs:
            parts = entry.get('content')
            if not isinstance(parts, list) or not parts or len(parts) > 2:
                raise ValueError('Use one image and/or one text component per visual input')
            for part in parts:
                if part.get('type') == 'text':
                    if set(part) != {'type','text'} or not isinstance(part['text'], str) or not part['text'].strip() or len(part['text'].encode('utf-8')) > 8191:
                        raise ValueError('Invalid bounded text input')
                elif part.get('type') == 'image_base64':
                    if set(part) != {'type','image_base64'} or not isinstance(part['image_base64'], str) or not part['image_base64'].startswith('data:image/png;base64,') or len(part['image_base64']) > MAX_IMAGE_BYTES * 4 // 3 + 100:
                        raise ValueError('Use a bounded local PNG data URL')
                else:
                    raise ValueError('Only local image data and text are accepted; remote image URLs are forbidden')
        cache = self.store.root / "derived/visual-embeddings" / digest(self.profile)[:16]
        cache.mkdir(parents=True, exist_ok=True)
        hashes = [digest([input_type, entry]) for entry in inputs]
        values: list[Any] = [None] * len(inputs)
        missing = []
        for index, checksum in enumerate(hashes):
            path = cache / (checksum + ".json")
            if path.is_file() and not probe:
                try:
                    values[index] = normalized(json.loads(path.read_text("utf-8")), self.dimensions)
                    continue
                except (ValueError, TypeError):
                    pass
            missing.append(index)
        if missing:
            request_hashes = [hashes[i] for i in missing]
            owner = self.owner or identity("visual_embedding", self.profile, request_hashes)
            inputs_identity = {"profile": self.profile, "input_type": input_type, "input_hashes": request_hashes}
            op_id = identity("operation", owner, "visual_embedding", inputs_identity)
            prior = self.store.one("SELECT * FROM operations WHERE id=?", (op_id,))
            if prior and prior["state"] != "complete":
                raise RuntimeError("Previous visual embedding attempt has unknown outcome; no automatic replay")
            op = self.store.reserve(owner, "visual_embedding", inputs_identity, tools=1, allowance=self.config.embedding_timeout)
            if op["state"] == "complete":
                vectors = json.loads(op["result"])["vectors"]
            else:
                client = self.client or httpx.Client(timeout=self.config.embedding_timeout, follow_redirects=False)
                try:
                    response = client.post(self.spec.endpoint, json=self.request_body([inputs[i] for i in missing], input_type),
                        headers={"Authorization": "Bearer " + key(self.config, self.spec)})
                    response.raise_for_status()
                    data = response.json()["data"]
                    rows = {row["index"]: row["embedding"] for row in data}
                    if len(data) != len(missing) or set(rows) != set(range(len(missing))):
                        raise ValueError("Visual embedding response indexes/count mismatch")
                    vectors = [normalized(rows[i], self.dimensions) for i in range(len(missing))]
                    self.store.complete_operation(op, {"vectors": vectors, "profile": self.profile})
                except Exception as exc:
                    raise RuntimeError(f"Visual embedding request failed ({type(exc).__name__}); no automatic retry") from None
                finally:
                    if self.client is None:
                        client.close()
            for index, vector in zip(missing, vectors, strict=True):
                values[index] = normalized(vector, self.dimensions)
                path = cache / (hashes[index] + ".json")
                temporary = cache / (digest([hashes[index], time.time_ns()]) + ".tmp")
                temporary.write_text(canonical(values[index]), "utf-8")
                temporary.replace(path)
        return values


def test_connection(store: Store, client: httpx.Client | None = None) -> dict:
    if store.one("SELECT id FROM outbox WHERE kind='embedding_reindex' AND state IN ('pending','running')"):
        raise ValueError('Wait for the current rebuild before re-testing the visual endpoint')
    embedder = VoyageVisualEmbedding(store, owner=new_id("job_visual_probe"), client=client)
    probe_inputs = []
    for shape, color in [("square", "red"), ("circle", "blue")]:
        image = Image.new("RGB", (256, 256), "white")
        draw = ImageDraw.Draw(image)
        getattr(draw, "rectangle" if shape == "square" else "ellipse")((40, 40, 215, 215), fill=color)
        stream = io.BytesIO()
        image.save(stream, "PNG")
        probe_inputs.append(content(image=stream.getvalue()))
    # An explicit re-test first revokes the prior capability until the current endpoint passes.
    store.execute("DELETE FROM workspace WHERE key=?", (capability_key(embedder.spec),))
    try:
        images = embedder.encode(probe_inputs, "document", probe=True)
        queries = embedder.encode([content("a red square"), content("a blue circle")], "query", probe=True)
        scores = [[sum(a*b for a, b in zip(query, image, strict=True)) for image in images] for query in queries]
        if scores[0][0] <= scores[0][1] + .001 or scores[1][1] <= scores[1][0] + .001:
            raise ValueError("Synthetic test could not verify aligned image/text retrieval")
        value = {"state": "verified", "profile": embedder.profile, "checked": time.time(), "scores": scores,
                 "evidence": "Two generated shapes and two text queries; no source assets transmitted"}
        store.execute("INSERT INTO workspace(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (capability_key(embedder.spec), canonical(value)))
        return {"status": "Synthetic image/text test passed. Rebuild the index after enabling image embeddings."}
    except Exception as exc:
        raise ValueError("Synthetic image test failed (" + type(exc).__name__ + "). No report pixels were transmitted; verify the deployment and its image-input support.") from None


def media_records(store: Store, document_id: str) -> list[dict]:
    rows = store.all("SELECT m.*,a.sha256,a.mime FROM media m JOIN assets a ON a.id=m.asset_id WHERE m.document_id=? ORDER BY m.id", (document_id,))
    for row in rows:
        captions = [row["caption"]]
        captions += [v["text"] for v in store.all("SELECT text FROM visuals WHERE media_id=? ORDER BY id", (row["id"],))]
        captions += [r["title"] or "" for r in store.all("SELECT DISTINCT i.title FROM unit_blocks ub JOIN units u ON u.id=ub.unit_id LEFT JOIN items i ON i.id=u.item_id WHERE ub.block_id=?", (row["block_id"],))]
        # Bound context by Unicode code points; source text remains unchanged and is not used as a quotation.
        row["context"] = "\n".join(captions)[:1500]
        row["context_hash"] = digest(row["context"])
    return rows


def source_identity(records: list[dict]) -> str:
    return digest([(r["id"], r["asset_id"], r["sha256"], r["context_hash"]) for r in records])


class VisualProjection:
    def __init__(self, store: Store, owner=None, embeddings=None):
        self.store = store
        self.embeddings = embeddings or VoyageVisualEmbedding(store, owner)

    def client(self):
        from qdrant_client import QdrantClient
        return QdrantClient(url=self.store.config.qdrant_url, api_key=self.store.config.qdrant_key or None, timeout=8)

    def collection(self):
        return "visuals_" + digest(self.embeddings.profile)[:20]

    def write(self, revision: str, records: list[dict]) -> dict:
        from qdrant_client import models
        skipped = []
        indexed = []
        with closing(self.client()) as client:
            collection = self.collection()
            if not client.collection_exists(collection):
                client.create_collection(collection, vectors_config=models.VectorParams(size=self.embeddings.dimensions, distance=models.Distance.COSINE))
            vector_config = client.get_collection(collection).config.params.vectors
            if not isinstance(vector_config, models.VectorParams) or vector_config.size != self.embeddings.dimensions:
                raise ValueError("Visual collection dimension/profile mismatch")
            for field in ["projection_revision_id", "document_version_id", "embedding_profile_id", "source_role"]:
                if field not in client.get_collection(collection).payload_schema:
                    client.create_payload_index(collection, field, models.PayloadSchemaType.KEYWORD)
            for start in range(0, len(records), 8):
                batch = []
                inputs = []
                for record in records[start:start + 8]:
                    raw = self.store.asset_path(record["asset_id"]).read_bytes()
                    if digest(raw) != record["sha256"]:
                        raise ValueError("Original image checksum mismatch")
                    try:
                        image = pixels(raw, self.store.config.max_pixels)
                    except ValueError as exc:
                        skipped.append({"media_id": record["id"], "reason": str(exc)})
                        continue
                    batch.append(record)
                    inputs.append(content(record["context"], image))
                if not batch:
                    continue
                vectors = self.embeddings.encode(inputs, "document")
                points = []
                for record, vector in zip(batch, vectors, strict=True):
                    payload = {"media_occurrence_id": record["id"], "asset_id": record["asset_id"],
                        "asset_hash": record["sha256"], "context_hash": record["context_hash"],
                        "document_version_id": record["document_id"], "projection_revision_id": revision,
                        "embedding_profile_id": self.embeddings.profile,
                        "source_role": self.store.require("SELECT role FROM documents WHERE id=?", (record["document_id"],))["role"]}
                    point_id = identity("visualpoint", revision, record["id"], self.embeddings.profile)
                    import uuid
                    points.append(models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, point_id)), vector=vector, payload=payload))
                    indexed.append(record["id"])
                client.upsert(collection, points, wait=True)
            actual = []
            offset = None
            while True:
                points, offset = client.scroll(collection, scroll_filter=models.Filter(must=[models.FieldCondition(
                    key="projection_revision_id", match=models.MatchValue(value=revision))]), limit=200, offset=offset, with_payload=True)
                actual += [p.payload["media_occurrence_id"] for p in points]
                if offset is None:
                    break
            if sorted(actual) != sorted(indexed):
                raise ValueError("Visual projection receipt mismatch")
        return {"state": "ready", "profile": self.embeddings.profile, "dimensions": self.embeddings.dimensions,
            "count": len(indexed), "total": len(records), "id_hash": digest(sorted(indexed)), "skipped": skipped,
            "coverage": "partial" if skipped else "complete", "source_hash": source_identity(records)}

    def search(self, question: str, revisions: list[str], limit=30) -> list[dict]:
        from qdrant_client import models
        with closing(self.client()) as client:
            if not revisions or not client.collection_exists(self.collection()):
                return []
            vector = self.embeddings.encode([content(question)], "query")[0]
            points = client.query_points(self.collection(), query=vector, query_filter=models.Filter(must=[
                models.FieldCondition(key="projection_revision_id", match=models.MatchAny(any=revisions)),
                models.FieldCondition(key="embedding_profile_id", match=models.MatchValue(value=self.embeddings.profile))]), limit=limit).points
            return [{"id": p.payload["media_occurrence_id"], "score": p.score, **p.payload} for p in points]
