import asyncio
import json
import time
from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from app.contracts import FactResponse, QuestionRequest, Rule, EditionReview, FragmentReview, ReferenceReview
from app.ingestion import register
from app.ontology import Ontology
from app.recovery import backup, restore
from app.retrieval import search, source, evidence_media, media_detail, finding_bundle, enumerate_findings, canonical_graph
from app.settings import ROOT, Settings, settings
from app.store import Store, canonical, identity, new_id
from app.verification import fact_context
from app.workflows import checkpoint_session, build_research, execute_research, RESEARCH_VERSION
from app.renditions import RenditionReview,confirm
from app.embeddings import public_settings as embedding_settings
from app.embedding_index import save_settings as save_embedding_settings, queue_reindex
from app import visual_embeddings as visual
from app.providers import chat_provider, text_credential, apply_saved_text_settings


class ReviewRequest(BaseModel):
    expected_version: int
    reason: str = Field(min_length=3, max_length=2000)
    corrected_value: str | None = Field(default=None, max_length=50000)
    state: str = "reviewed"


class ProjectRequest(BaseModel):
    label: str = Field(min_length=1, max_length=150)
    parts: list[str] = Field(default_factory=lambda: ["Whole building"])


class ContextRequest(BaseModel):
    expected_version: int
    part_id: str
    purpose: str
    facts: dict[str, list[dict]]


class SettingsRequest(BaseModel):
    expected_version: int
    text_provider: str = "disabled"
    text_endpoint: str = "https://api.openai.com/v1"
    text_model: str = ""
    verifier_model: str = ""
    vision_enabled: bool = False
    vision_endpoint: str = ""
    tool_limit: int = Field(default=20, ge=1, le=50)
    round_limit: int = Field(default=3, ge=1, le=5)
    active_seconds: int = Field(default=120, ge=10, le=600)
    model_timeout: float = Field(default=90, ge=10, le=180)


class EmbeddingSettingsRequest(BaseModel):
    expected_version: int
    embedding_provider: str
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=0, ge=0, le=4096)


class VisualEmbeddingSettingsRequest(BaseModel):
    expected_version: int
    visual_embedding_provider: str = 'disabled'
    visual_embedding_deployment: str = ''
    visual_embedding_dimensions: int = Field(default=1024, ge=1, le=2048)
    visual_embedding_enabled: bool = False


def create_app(config: Settings = settings):
    store = Store(config)
    store.initialize()
    apply_saved_text_settings(store)
    ontology = Ontology(store)

    @asynccontextmanager
    async def lifespan(api):
        api.state.store = store
        api.state.checkpoint_status = "unavailable"
        api.state.checkpoint_reason = ""
        api.state.graph = None
        api.state.resumes = {}
        async with AsyncExitStack() as stack:
            try:
                saver = await stack.enter_async_context(checkpoint_session(store))
                api.state.graph = build_research(store, saver, ontology)
                api.state.checkpoint_status = "development_sqlite" if config.checkpoint_backend == "sqlite-dev" else "ready"
            except Exception as exc:
                api.state.checkpoint_reason = type(exc).__name__ + ": checkpoint service/configuration unavailable"
            store.execute("UPDATE runs SET status='queued',error='Resuming compatible persisted execution after restart' WHERE status='running' AND graph_version=?", (RESEARCH_VERSION,))

            async def scheduler():
                while True:
                    if api.state.graph:
                        maintenance=store.one("SELECT value FROM workspace WHERE key='maintenance'")
                        if maintenance and maintenance['value']=='1':
                            await asyncio.sleep(.25)
                            continue
                        run = store.one("SELECT * FROM runs WHERE status='queued' ORDER BY created LIMIT 1")
                        if run:
                            if run["graph_version"] != RESEARCH_VERSION or not store.one("SELECT id FROM manifests WHERE id=?", (run["manifest_id"],)):
                                store.execute("UPDATE runs SET status='interrupted',error='Incompatible graph/manifest; new run required' WHERE id=?", (run["id"],))
                            else:
                                await execute_research(store, api.state.graph, run["id"], api.state.resumes.pop(run["id"], None))
                    await asyncio.sleep(.25)
            task = asyncio.create_task(scheduler())
            try:
                yield
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    api = FastAPI(title="Defect Intelligence", version="0.1.0", lifespan=lifespan)

    @api.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()
        if host not in {"localhost", "127.0.0.1", "testserver"}:
            return JSONResponse({"code": "local_boundary", "message": "Local host required"}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            maintenance=store.one("SELECT value FROM workspace WHERE key='maintenance'")
            if maintenance and maintenance['value']=='1':
                return JSONResponse({'code':'maintenance','message':'Workspace recovery in progress'},status_code=409)
            origin = request.headers.get("origin")
            if origin and urlparse(origin).hostname not in {"localhost", "127.0.0.1"}:
                return JSONResponse({"code": "origin_rejected", "message": "Same local origin required"}, status_code=403)
            if request.headers.get("x-workspace-request") != "1":
                return JSONResponse({"code": "request_boundary", "message": "Workspace request header required"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @api.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"code": "unknown_id", "message": str(exc), "retryable": False}, status_code=404)

    @api.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"code": "invalid_input", "message": str(exc), "retryable": False}, status_code=400)

    @api.get("/api/health")
    async def health():
        counts = {name: store.require("SELECT COUNT(*) n FROM " + name)["n"] for name in ["documents", "findings", "media", "reviews", "runs", "demands"]}
        import httpx
        services = {"catalog": "ready", "fts": "ready", "ontology": ontology.version,
            "checkpoints": getattr(api.state, "checkpoint_status", "not_started"),
            "checkpoint_reason": getattr(api.state, "checkpoint_reason", ""),
            "neo4j": "unconfigured", "qdrant": "unconfigured",
            "local_embeddings": "configured" if config.embedding_path else "unconfigured",
            "text_provider": config.text_provider, "vision": "disabled", "regulatory_rules": "no reviewed coverage"}
        embeddings = embedding_settings(store)
        services["embedding_provider"] = embeddings["embedding_provider"]
        services["embedding_index"] = embeddings["index_state"]
        visual_state = visual.public_settings(store)
        services["image_embeddings"] = visual_state['index_state']
        services['visual_embedding_provider'] = visual_state['visual_embedding_provider']
        processing = 'Hosted image embeddings selected' if visual_state['visual_embedding_enabled'] else (
            'Hosted text processing selected' if config.text_provider != 'disabled' or embeddings['embedding_provider'] in {'openai','fireworks'} else 'Local processing')
        if config.qdrant_url:
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    response = await client.get(config.qdrant_url + "/readyz", headers={"api-key": config.qdrant_key} if config.qdrant_key else {})
                services["qdrant"] = "ready" if response.is_success else "unavailable"
            except Exception:
                services["qdrant"] = "unavailable"
        if config.neo4j_uri:
            from app.projections import NeoProjection
            def check_neo():
                with NeoProjection(store).driver() as driver:
                    driver.verify_connectivity()
            try:
                await asyncio.wait_for(asyncio.to_thread(check_neo), 5)
                services["neo4j"] = "ready"
            except Exception:
                services["neo4j"] = "unavailable"
        worker = store.one("SELECT value FROM workspace WHERE key='worker_heartbeat'")
        services["worker"] = "ready" if worker and time.time() - float(worker["value"]) < 45 else "offline"
        return {"status": "partial", "processing": processing, "counts": counts, "services": services, "manifest_id": store.active_manifest(),
                "warnings": ["Historical evidence and regulatory applicability are separate", "No real regulatory coverage activated"]}

    @api.post("/api/imports", status_code=202)
    async def imports(files: list[UploadFile] = File(...), role: str = Form("company_report"), family_id: str | None = Form(None), metadata: str = Form("{}")):
        results = []
        for upload in files[:100]:
            data = bytearray()
            while chunk := await upload.read(1024**2):
                data.extend(chunk)
                if len(data) > config.upload_limit_mb * 1024**2:
                    break
            try:
                result = await asyncio.to_thread(register, bytes(data), upload.filename or "unknown", role, store, family_id, json.loads(metadata))
                results.append({"filename": upload.filename, **result})
            except (ValueError, json.JSONDecodeError) as exc:
                results.append({"filename": upload.filename, "status": "rejected", "error": str(exc)})
            await upload.close()
        return {"items": results}

    @api.get("/api/imports")
    async def jobs():
        return {"items": store.all("SELECT j.*,d.filename FROM jobs j JOIN documents d ON d.id=j.document_id ORDER BY j.created DESC LIMIT 100")}

    @api.post("/api/imports/{job_id}/cancel")
    async def cancel_job(job_id: str):
        if not store.one("SELECT id FROM jobs WHERE id=?", (job_id,)):
            raise KeyError("Unknown import job")
        store.execute("UPDATE jobs SET cancel=1,status=CASE WHEN lease_owner IS NULL THEN 'cancelled' ELSE status END WHERE id=?", (job_id,))
        store.execute("UPDATE budgets SET cancel=1 WHERE owner_id=?", (job_id,))
        return {"status": "cancellation_requested"}

    @api.post("/api/imports/{job_id}/retry")
    async def retry_job(job_id: str):
        job = store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job:
            raise KeyError("Unknown import job")
        if job["lease_owner"] or job["attempts"] >= 3:
            raise HTTPException(409, "Active lease or cumulative attempt budget exhausted")
        store.execute("UPDATE jobs SET status='queued',cancel=0,error=NULL WHERE id=?", (job_id,))
        store.execute("UPDATE budgets SET cancel=0 WHERE owner_id=?", (job_id,))
        return {"status": "queued", "budgets": "retained"}

    async def event_stream(owner: str, request: Request, after: int):
        while not await request.is_disconnected():
            events = store.all("SELECT * FROM events WHERE owner_id=? AND sequence>? ORDER BY sequence LIMIT 100", (owner, after))
            for e in events:
                after = e["sequence"]
                yield "id: " + str(after) + "\nevent: " + e["type"] + "\ndata: " + canonical({**e, "payload": json.loads(e["payload"])}) + "\n\n"
            yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    @api.get("/api/imports/{owner}/events")
    @api.get("/api/runs/{owner}/events")
    async def events(owner: str, request: Request, after: int = 0):
        if not store.one("SELECT id FROM jobs WHERE id=? UNION SELECT id FROM runs WHERE id=?", (owner, owner)):
            raise KeyError("Unknown event owner")
        after = max(after, int(request.headers.get("last-event-id", "0")))
        return StreamingResponse(event_stream(owner, request, after), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @api.get("/api/events/{owner}")
    async def event_history(owner: str):
        return {"items": [{**e, "payload": json.loads(e["payload"])} for e in store.all("SELECT * FROM events WHERE owner_id=? ORDER BY sequence", (owner,))]}

    @api.get("/api/documents")
    async def documents():
        return {"items": [{**d, "metadata": json.loads(d["metadata"]),
            "media_count": store.require("SELECT COUNT(*) n FROM media WHERE document_id=?", (d["id"],))["n"]} for d in store.all("SELECT * FROM documents ORDER BY created DESC")], "manifest_id": store.active_manifest()}

    @api.post('/api/rendition-mappings',status_code=201)
    async def rendition_mapping(body:RenditionReview):
        return confirm(store,body)

    @api.get('/api/rendition-mappings')
    async def rendition_mappings():
        return {'items':store.all('SELECT * FROM finding_equivalences')}

    @api.get("/api/documents/{doc_id}")
    async def document_detail(doc_id: str, cursor: int = 0, limit: int = Query(50, ge=1, le=100)):
        d = store.one("SELECT * FROM documents WHERE id=?", (doc_id,))
        if not d:
            raise KeyError("Unknown document")
        blocks = store.all("SELECT b.*,a.id anchor_id FROM blocks b JOIN anchors a ON a.block_id=b.id WHERE b.document_id=? ORDER BY sequence LIMIT ? OFFSET ?", (doc_id, limit, cursor))
        return {"document": d, "blocks": blocks, "next_cursor": cursor + limit if len(blocks) == limit else None}

    @api.post("/api/documents/{doc_id}/archive")
    async def archive(doc_id: str):
        if not store.one("SELECT id FROM documents WHERE id=?", (doc_id,)):
            raise KeyError("Unknown document")
        store.archive(doc_id)
        return {"status": "archived", "manifest_id": store.active_manifest()}

    @api.get("/api/search")
    async def search_api(q: str = "", limit: int = Query(30, ge=1, le=100), document_id: str | None = None, content_kind: str | None = None):
        return await asyncio.to_thread(search, store, ontology, q, None, limit, document_id, content_kind)

    @api.get("/api/findings")
    async def findings(q: str = "", cursor: int = 0, limit: int = Query(30, ge=1, le=100), document_id: str | None = None):
        result = enumerate_findings(store, q, offset=cursor, limit=limit, document_id=document_id)
        if q and not result["total"]:
            candidates = await asyncio.to_thread(search, store, ontology, q, None, 100, document_id)
            item_ids = sorted({c["metadata"]["defect_item_id"] for c in candidates["items"] if c["metadata"].get("defect_item_id")})
            rows = store.all("SELECT f.*,i.title,d.filename FROM findings f JOIN items i ON i.id=f.item_id JOIN documents d ON d.id=f.document_id WHERE f.item_id IN (" + ",".join("?" for _ in item_ids) + ") ORDER BY f.id", item_ids) if item_ids else []
            result.update({"items": rows[cursor:cursor+limit], "total": len(rows), "next_cursor": str(cursor+limit) if cursor+limit<len(rows) else None,
                "coverage": "Hybrid/catalog candidate scope; complete enumeration requires exact filters", "warnings": candidates["warnings"]})
        return result

    @api.get("/api/findings/{fid}")
    async def finding(fid: str):
        return finding_bundle(store, fid)

    @api.get("/api/defect-items/{iid}")
    async def item(iid: str):
        row = store.one("SELECT * FROM items WHERE id=?", (iid,))
        if not row:
            raise KeyError("Unknown defect item")
        return {**row, "occurrences": store.all("SELECT * FROM findings WHERE item_id=?", (iid,)),
                "sections": store.all("SELECT u.*,p.text FROM units u JOIN parents p ON p.id=u.parent_id WHERE item_id=?", (iid,))}

    @api.get("/api/ontology")
    async def concepts(q: str = ""):
        catalog = ontology.public_model()
        if q:
            catalog['search_vocabulary']['items'] = ontology.resolve(q, q)
        return catalog

    @api.get('/api/ontology/classes/{class_id}/instances')
    async def domain_instances(class_id: str, q: str = '', limit: int = Query(30,ge=1,le=100), offset: int = Query(0,ge=0)):
        from app.domain import instance_catalog
        return await asyncio.to_thread(instance_catalog,store,ontology.domain_model,class_id,q,limit,offset)

    @api.get('/api/ontology/schema')
    async def shared_schema():
        return ontology.public_schema()

    @api.get('/api/search-vocabulary')
    async def search_vocabulary():
        return ontology.public_catalog()

    @api.get('/api/domain/classes/{class_id}/records')
    async def class_records(class_id: str, q: str = '', limit: int = Query(30,ge=1,le=100), offset: int = Query(0,ge=0)):
        from app.domain import instance_catalog
        return await asyncio.to_thread(instance_catalog,store,ontology.domain_model,class_id,q,limit,offset)

    @api.get('/api/knowledge-graph')
    async def domain_graph(entity_id: str, limit: int = Query(50,ge=10,le=100)):
        from app.domain import published_snapshots
        from app.projections import NeoProjection
        snapshots = published_snapshots(store)
        record = next((r for s in snapshots for r in s['records'] if r['id']==entity_id),None)
        if not record:
            raise KeyError('Domain entity is not in the published report graph')
        revisions = [r['projection_id'] for r in store.all('SELECT projection_id FROM manifest_members WHERE manifest_id=?',(store.active_manifest(),))]
        if not config.neo4j_uri:
            raise ValueError('Neo4j must be connected to explore the domain graph')
        result = await asyncio.to_thread(NeoProjection(store).explore,[entity_id],revisions,limit)
        return {**result,'root':record}

    @api.get("/api/evidence-media")
    async def images(q: str = "", cursor: int = 0, limit: int = Query(24, ge=1, le=60), role: str | None = None):
        return await asyncio.to_thread(evidence_media,store,ontology,q,None,limit,cursor,role)

    @api.get("/api/source-anchors/{anchor_id}")
    async def anchor(anchor_id: str):
        return source(store, anchor_id)

    @api.get("/api/media-occurrences/{media_id}")
    async def image(media_id: str):
        return media_detail(store, media_id)

    @api.get("/api/assets/{asset_id}/content")
    async def content(asset_id: str):
        asset = store.one("SELECT * FROM assets WHERE id=?", (asset_id,))
        if not asset:
            raise KeyError("Unknown managed asset")
        inline = asset["mime"] in {"image/png", "image/jpeg", "image/gif", "application/pdf"}
        metadata = json.loads(asset['metadata'])
        filename = metadata.get('original_filename') or (asset_id + store.asset_path(asset_id).suffix)
        return FileResponse(store.asset_path(asset_id), media_type=asset["mime"] if inline else "application/octet-stream",
                            content_disposition_type="inline" if inline else "attachment", filename=filename)

    @api.get("/api/findings/{fid}/graph")
    async def graph(fid: str, limit: int = Query(100, ge=10, le=100)):
        if config.neo4j_uri:
            from app.projections import NeoProjection
            finding=finding_bundle(store,fid)
            revisions=[r['projection_id'] for r in store.all('SELECT projection_id FROM manifest_members WHERE manifest_id=?',(store.active_manifest(),))]
            try:
                result=await asyncio.to_thread(NeoProjection(store).explore,[fid,finding['item_id']],revisions,limit)
                if result['nodes']:
                    return result
            except Exception:
                pass
        return canonical_graph(store, fid, limit)

    @api.get("/api/projects")
    async def projects():
        return {"items": [{**p, "parts": store.all("SELECT * FROM parts WHERE project_id=?", (p["id"],))} for p in store.all("SELECT * FROM projects")]}

    @api.post("/api/projects", status_code=201)
    async def project_create(body: ProjectRequest):
        pid = new_id("project")
        store.insert("projects", {"id": pid, "label": body.label, "version": 1})
        for label in body.parts[:30]:
            part_id = new_id("part")
            store.insert("parts", {"id": part_id, "project_id": pid, "label": label})
            for purpose in ["original_work_assessment", "proposed_remedial_work"]:
                store.insert("contexts", {"id": new_id("context"), "project_id": pid, "part_id": part_id, "purpose": purpose,
                    "version": 1, "facts": {}, "created": time.time()})
        return {"id": pid}

    @api.get("/api/projects/{pid}/context")
    async def project_context(pid: str):
        project = store.one("SELECT * FROM projects WHERE id=?", (pid,))
        if not project:
            raise KeyError("Unknown project")
        return {"project": project, "parts": store.all("SELECT * FROM parts WHERE project_id=?", (pid,)),
            "contexts": [{**c, "facts": json.loads(c["facts"])} for c in store.all("SELECT * FROM contexts WHERE project_id=? ORDER BY version DESC", (pid,))]}

    @api.put("/api/projects/{pid}/context")
    async def context_edit(pid: str, body: ContextRequest):
        part = store.one("SELECT * FROM parts WHERE id=? AND project_id=?", (body.part_id, pid))
        if not part or body.purpose not in {"original_work_assessment", "proposed_remedial_work"}:
            raise ValueError("Invalid part or work context")
        latest = store.one("SELECT * FROM contexts WHERE project_id=? AND part_id=? AND purpose=? ORDER BY version DESC LIMIT 1", (pid, body.part_id, body.purpose))
        if not latest or latest["version"] != body.expected_version:
            raise HTTPException(409, "Stale context version")
        for key, values in body.facts.items():
            if key == "building_class" and any("finish" in str(v).lower() or "membrane" in str(v).lower() for v in values):
                raise ValueError("Concrete finish and membrane classes are distinct from building classification")
            for fact in values:
                if fact.get("kind") not in {"user_declaration", "reviewed_project_fact"} or not fact.get("provenance"):
                    raise ValueError("Every fact requires attribution/provenance")
                if fact["kind"] == "reviewed_project_fact" and not store.one("SELECT id FROM anchors WHERE id=?", (fact.get("anchor_id"),)):
                    raise ValueError("Reviewed project fact requires existing source support")
        cid = identity("context", latest["id"], body.model_dump())
        with store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT MAX(version) FROM contexts WHERE project_id=? AND part_id=? AND purpose=?", (pid, body.part_id, body.purpose)).fetchone()[0]
            if current != body.expected_version:
                raise HTTPException(409, "Concurrent context change")
            store.insert("contexts", {"id": cid, "project_id": pid, "part_id": body.part_id, "purpose": body.purpose,
                "version": current + 1, "facts": body.facts, "created": time.time()}, con)
            con.execute("UPDATE runs SET stale=1 WHERE project_id=? AND part_id=?", (pid, body.part_id))
        return {"context_id": cid, "version": body.expected_version + 1}

    @api.post("/api/questions", status_code=202)
    async def question(body: QuestionRequest):
        existing = store.one("SELECT * FROM runs WHERE client_id=?", (body.client_request_id,))
        if existing:
            if existing["question"] != body.question or existing["mode"] != body.mode:
                raise HTTPException(409, "Request ID already used for different question")
            return {"run_id": existing["id"], "events_url": "/api/runs/" + existing["id"] + "/events"}
        if not getattr(api.state, "graph", None):
            raise HTTPException(503, "Workflow checkpoint service unavailable; local source search is available")
        ctx = fact_context(store, body.project_id, body.part_id, body.mode)
        if body.project_id and not ctx:
            raise ValueError("Select a valid building part/work context")
        if ctx and body.context_version is not None and ctx["version"] != body.context_version:
            raise HTTPException(409, "Context changed; refresh before starting research")
        rid = new_id("run")
        store.insert("runs", {"id": rid, "client_id": body.client_request_id, "question": body.question, "mode": body.mode,
            "project_id": body.project_id, "part_id": body.part_id, "initial_context_id": ctx["id"] if ctx else None,
            "final_context_id": ctx["id"] if ctx else None, "manifest_id": store.active_manifest(), "graph_version": RESEARCH_VERSION,
            "status": "queued", "created": time.time(), "evidence": {}, "answer": {}})
        if body.mode == 'draft':
            facts = {k: values[0] for k, values in json.loads(ctx['facts']).items() if len(values) == 1} if ctx else {}
            store.insert('run_drafting', {'run_id': rid, 'facts': facts})
        store.execute("UPDATE runs SET rule_pack_ids=?,ontology_version=? WHERE id=?",
            (canonical([r["id"] for r in store.all("SELECT id FROM rules WHERE state='active'")]), ontology.version, rid))
        store.event(rid, "queued", {"mode": body.mode})
        return {"run_id": rid, "events_url": "/api/runs/" + rid + "/events"}

    @api.get("/api/runs")
    async def runs():
        return {"items": store.all("SELECT id,question,mode,status,stale,created,manifest_id,initial_context_id,final_context_id FROM runs ORDER BY created DESC LIMIT 100")}

    @api.get("/api/runs/{rid}")
    async def run(rid: str):
        r = store.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r:
            raise KeyError("Unknown saved run")
        r["answer"], r["evidence"] = json.loads(r["answer"]), json.loads(r["evidence"])
        if r['mode'] == 'draft':
            from app.drafting import drafting_record
            record = drafting_record(store, rid)
            r['draft_context'] = {'version': record['version'], 'facts': record['facts'], 'conversation': record['conversation']}
        r['answer'].setdefault('tool_calls', [{'sequence': e['sequence'], 'payload': json.loads(e['payload'])}
            for e in store.all("SELECT sequence,payload FROM events WHERE owner_id=? AND type='tool_completed' ORDER BY sequence", (rid,))])
        r["operations"] = store.all("SELECT id,node,state,tool_cost,seconds_reserved,started,finished FROM operations WHERE owner_id=? ORDER BY started", (rid,))
        return r

    @api.get("/api/runs/{rid}/report-sections")
    async def report_sections(rid: str):
        from app.report_sections import original_report_sections
        return await asyncio.to_thread(original_report_sections, store, rid)

    @api.post("/api/runs/{rid}/cancel")
    async def cancel_run(rid: str):
        if not store.one("SELECT id FROM runs WHERE id=?", (rid,)):
            raise KeyError("Unknown run")
        store.execute("UPDATE runs SET cancel=1,status=CASE WHEN status='queued' OR status='clarification_required' THEN 'cancelled' ELSE status END WHERE id=?", (rid,))
        store.execute("UPDATE budgets SET cancel=1 WHERE owner_id=?", (rid,))
        store.event(rid, "cancel_requested", {})
        return {"status": "cancellation_requested"}

    @api.post("/api/runs/{rid}/resume", status_code=202)
    async def resume_run(rid: str, body: FactResponse):
        r = store.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r or r["status"] != "clarification_required":
            raise HTTPException(409, "Run is not waiting for facts")
        if r['graph_version'] != RESEARCH_VERSION:
            raise HTTPException(409, 'This saved run uses an older workflow; start a new run')
        if r['mode'] == 'draft':
            from app.drafting import drafting_record, validate_chat_response
            record = drafting_record(store, rid)
            if record['version'] != body.expected_context_version or r['stale'] or r['manifest_id'] != store.active_manifest():
                raise HTTPException(409, 'The drafting context or library changed; start a new run')
            if r['project_id']:
                latest = fact_context(store, r['project_id'], r['part_id'], r['mode'])
                if not latest or latest['id'] != r['final_context_id']:
                    raise HTTPException(409, 'Project facts changed while paused; start a new run')
            validate_chat_response(record, body)
            with store.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                changed = con.execute("UPDATE runs SET status='queued' WHERE id=? AND status='clarification_required'", (rid,)).rowcount
                if not changed:
                    raise HTTPException(409, 'These answers were already submitted')
                con.execute('UPDATE run_drafting SET pending_response=? WHERE run_id=?', (canonical(body.model_dump()), rid))
            return {'status': 'queued', 'budget': 'retained'}
        ctx = store.require("SELECT * FROM contexts WHERE id=?", (r["final_context_id"],))
        latest = fact_context(store, r["project_id"], r["part_id"], r["mode"])
        if not latest or r["manifest_id"] != store.active_manifest() or latest["id"] != ctx["id"] or ctx["version"] != body.expected_context_version or r["stale"]:
            raise HTTPException(409, "Context/manifest changed while paused; start a new run")
        api.state.resumes[rid] = body.model_dump()
        store.execute("UPDATE runs SET status='queued' WHERE id=?", (rid,))
        return {"status": "queued", "budget": "retained"}

    @api.get("/api/review-items")
    async def reviews(state: str = "needs_review", limit: int = Query(50, ge=1, le=100)):
        rows = store.all("SELECT * FROM reviews WHERE state=? ORDER BY rowid LIMIT ?", (state, limit))
        return {"items": [{**r, "anchor_ids": json.loads(r["anchor_ids"])} for r in rows]}

    @api.get('/api/assertions')
    async def assertion_list(limit:int=Query(50,ge=1,le=100),document_id:str|None=None):
        rows=store.all("SELECT a.*,e.label subject_label FROM assertions a JOIN entities e ON e.id=a.subject_id WHERE a.state<>'superseded' AND (? IS NULL OR a.document_id=?) ORDER BY a.rowid LIMIT ?",(document_id,document_id,limit))
        for row in rows:
            row['anchor_ids']=[r['anchor_id'] for r in store.all('SELECT anchor_id FROM assertion_support WHERE assertion_id=?',(row['id'],))]
        return {'items':rows}

    @api.post("/api/review-items/{review_id}")
    @api.post("/api/assertions/{review_id}/reviews")
    async def review_edit(review_id: str, body: ReviewRequest):
        review = store.one("SELECT * FROM reviews WHERE id=? OR assertion_id=? ORDER BY version DESC LIMIT 1", (review_id, review_id))
        if not review:
            assertion=store.require('SELECT * FROM assertions WHERE id=?',(review_id,))
            if assertion['state']=='superseded':
                raise HTTPException(409,'Assertion superseded; inspect its successor')
            review={'id':identity('review',review_id),'document_id':assertion['document_id'],'assertion_id':review_id,
                'kind':'source_assertion','message':'Review extracted '+assertion['predicate'],
                'anchor_ids':[r['anchor_id'] for r in store.all('SELECT anchor_id FROM assertion_support WHERE assertion_id=?',(review_id,))],
                'state':'needs_review','version':assertion['version'],'payload':{}}
            store.insert('reviews',review)
        with store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT * FROM reviews WHERE id=?", (review["id"],)).fetchone()
            if current["version"] != body.expected_version:
                raise HTTPException(409, "Stale review version")
            successor = None
            if body.corrected_value is not None and review["assertion_id"]:
                old = store.require("SELECT * FROM assertions WHERE id=?", (review["assertion_id"],))
                successor = identity("assertion", old["id"], body.model_dump())
                new = {**old, "id": successor, "value": body.corrected_value, "version": old["version"] + 1,
                       "predecessor_id": old["id"], "state": "reviewed", "payload": json.loads(old["payload"])}
                store.insert("assertions", new, con)
                con.execute("UPDATE assertions SET state='superseded' WHERE id=?", (old["id"],))
                for s in con.execute("SELECT anchor_id FROM assertion_support WHERE assertion_id=?", (old["id"],)).fetchall():
                    store.insert("assertion_support", {"assertion_id": successor, "anchor_id": s[0]}, con)
            con.execute("UPDATE reviews SET state='reviewed',version=version+1,payload=? WHERE id=?", (canonical(body.model_dump()), review["id"]))
            store.insert("audits", {"id": new_id("audit"), "review_id": review["id"], "predecessor_id": review["assertion_id"],
                "successor_id": successor, "reason": body.reason, "created": time.time(), "payload": body.model_dump()}, con)
            con.execute("UPDATE runs SET stale=1 WHERE id IN (SELECT run_id FROM run_dependencies WHERE dependency_id IN (?,?))", (review["document_id"], review["assertion_id"]))
            store.insert("outbox", {"id": new_id("outbox"), "kind": "correction_reprojection", "payload": {"document_id": review["document_id"], "successor_id": successor}, "state": "pending"}, con)
        return {"status": "reviewed", "version": body.expected_version + 1, "projection_status": "pending_rebuild", "successor_id": successor}

    @api.get("/api/reference-coverage")
    async def coverage():
        return {"disposition": "unresolved", "references": [{**r, "identity": json.loads(r["identity_json"])} for r in store.all("SELECT * FROM references_catalog ORDER BY label LIMIT 1000")],
            "editions": store.all("SELECT * FROM reference_editions"), "fragments": store.all("SELECT * FROM reference_fragments"),
            "relationships": store.all("SELECT * FROM reference_relationships"),
            "rules": store.all("SELECT id,version,state FROM rules"), "note": "Imported/cited sources do not establish adoption or exact reference-chain coverage"}

    @api.post("/api/reference-editions", status_code=201)
    async def edition_review(body: EditionReview):
        from app.references import review_edition
        return review_edition(store, body)

    @api.post("/api/reference-fragments", status_code=201)
    async def fragment_review(body: FragmentReview):
        from app.references import review_fragment
        return review_fragment(store, body)

    @api.post("/api/reference-relationships", status_code=201)
    async def relationship_review(body: ReferenceReview):
        from app.references import review_relationship
        return review_relationship(store, body)

    @api.get("/api/reference-demands")
    async def demands():
        return {"items": store.all("SELECT label,state,COUNT(*) count FROM demands GROUP BY label,state ORDER BY label")}

    @api.post("/api/rules/{rule_id}/reviews")
    async def rule_review(rule_id: str, rule: Rule):
        from app.applicability import validate_activation
        if rule.id != rule_id:
            raise ValueError("Rule identity mismatch")
        validate_activation(rule, store)
        existing = store.one("SELECT * FROM rules WHERE id=?", (rule_id,))
        if existing:
            raise HTTPException(409, "Rule version identity already exists; retain history and submit a new version ID")
        rule = rule.model_copy(update={"state":"active"})
        store.insert("rules", {"id": rule.id, "version": rule.version, "payload": rule.model_dump(mode="json"), "state": "active"})
        store.execute("UPDATE runs SET stale=1")
        return {"status": "active", "scope": "only reviewed rule premises; original fragment/chain checks still required"}

    @api.get('/api/visual-embedding-settings')
    async def get_visual_embedding_settings():
        return visual.public_settings(store)

    @api.put('/api/visual-embedding-settings')
    async def put_visual_embedding_settings(body: VisualEmbeddingSettingsRequest):
        return visual.save_settings(store, body.model_dump())

    @api.post('/api/visual-embedding-settings/test')
    async def test_visual_embedding_endpoint():
        return await asyncio.to_thread(visual.test_connection, store)

    @api.get("/api/embedding-settings")
    async def get_embedding_settings():
        return embedding_settings(store)

    @api.put("/api/embedding-settings")
    async def put_embedding_settings(body: EmbeddingSettingsRequest):
        return save_embedding_settings(store, body.model_dump())

    @api.post("/api/embedding-settings/reindex", status_code=202)
    async def reindex_embeddings():
        return queue_reindex(store)

    @api.get("/api/settings")
    async def get_settings():
        existing = store.one("SELECT value FROM workspace WHERE key='settings'")
        payload = json.loads(existing["value"]) if existing else {"version": 1}
        return {"version": payload["version"], "text_provider": config.text_provider, "text_endpoint": config.text_endpoint,
            "text_model": config.text_model, "verifier_model": config.verifier_model, "vision_enabled": config.vision_enabled,
            "vision_endpoint": config.vision_endpoint, "credential_configured": bool(text_credential(config)),
            "openai_key_configured": bool(config.openai_api_key), "fireworks_key_configured": bool(config.fireworks_api_key),
            "tool_limit": config.tool_limit, "round_limit": config.round_limit, "active_seconds": config.active_seconds,
            'model_timeout':config.model_timeout,
            "pricing": "unknown", "checkpoint_backend": config.checkpoint_backend,
            "transmission": "No originals or pixels; selected text only when explicitly enabled"}

    @api.put("/api/settings")
    async def put_settings(body: SettingsRequest):
        current = await get_settings()
        if current["version"] != body.expected_version:
            raise HTTPException(409, "Stale settings version")
        if store.one("SELECT id FROM runs WHERE status IN ('queued','running') LIMIT 1"):
            raise HTTPException(409, 'Wait for active research to finish before changing provider settings')
        if body.text_provider not in {"disabled", "openai", "fireworks", "compatible"}:
            raise ValueError("Unknown provider")
        if body.text_provider != "disabled" and (not text_credential(config, body.text_provider) or not body.text_model or not body.verifier_model):
            raise ValueError("Configure credential server-side and both model profiles before enabling text transmission")
        if body.vision_enabled:
            raise ValueError("Vision adapter capability validation required before pixel transmission; local OCR remains enabled")
        payload = {"version": body.expected_version + 1, **body.model_dump(exclude={"expected_version"})}
        with store.connect() as con:
            con.execute("INSERT INTO workspace(key,value) VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (canonical(payload),))
        for key, value in body.model_dump(exclude={"expected_version"}).items():
            setattr(config, key, value)
        return {"version": payload["version"], "status": "saved", "worker": "restart worker to apply provider/profile changes"}

    @api.post('/api/settings/test')
    async def test_text_provider():
        class Probe(BaseModel):
            answer: str
        port = chat_provider(config)
        try:
            result = await port.generate_structured(Probe, [{'role': 'user', 'content': 'Reply with the word connected in the answer field.'}],
                                                    {'seconds': 30, 'tokens': 300})
        except Exception as exc:
            raise HTTPException(400, f'Provider connection/structured-output test failed: {type(exc).__name__}') from None
        return {'status': 'connected', 'provider': config.text_provider, 'model': config.text_model,
                'structured_output': bool(result.answer), 'receipt': getattr(port, 'receipt', {})}

    @api.post("/api/backups", status_code=201)
    async def backup_api():
        return await asyncio.to_thread(backup, store)

    @api.get("/api/backups")
    async def backups_api():
        return {"items": [{"id": r["key"], "metadata": json.loads(r["value"])["manifest"]} for r in store.all("SELECT * FROM workspace WHERE key LIKE 'backup_%'")]}

    @api.post("/api/restores")
    async def restore_api(body: dict):
        return await asyncio.to_thread(restore, store, body.get("backup_id", ""))

    @api.get("/{path:path}")
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Unknown API endpoint")
        webroot = ROOT / "web/dist"
        target = (webroot / path).resolve()
        if not target.is_relative_to(webroot.resolve()):
            raise HTTPException(404)
        if path and target.is_file():
            return FileResponse(target)
        if (webroot / "index.html").exists():
            return FileResponse(webroot / "index.html")
        return JSONResponse({"message": "Build the frontend or start the Vite development server"})

    return api


app = create_app()
