# Defect Intelligence

A working local application for researching previous Word/PDF defect reports, original visuals, authored reasoning, references and repair alternatives. The representative sample is privately imported. This machine now uses live Fireworks text research and Qwen text embeddings. Image-pixel processing remains separately disabled; fresh installations default to disabled external processing.

**Status: runnable pilot, not an accepted regulatory release.** Source indexing and browsing work; partial extraction remains labelled awaiting configuration. Original references, reviewed rules, expert scope review and the held-out pilot evaluation remain required. See [VALIDATION.md](VALIDATION.md) for executed checks and specific limits.

## Start on this machine

Open PowerShell in this folder:

```powershell
.\start-app.ps1 -Native
```

Open [Defect Intelligence](http://127.0.0.1:8000). The helper starts the installed portable PostgreSQL, Neo4j and Qdrant services when needed, then the API and durable worker. All listeners bind to localhost. The native API uses a Windows selector event loop compatible with psycopg. Startup never seeds or deletes company data.

This workspace already has the locked Python environment, built React application, local BGE/Docling/OCR caches and portable service runtimes. Credentials, service data, extracted records and caches remain private in `.env`, `data/`, `.cache/` and `.tools/`, excluded from source control. Logs are in `data/logs/`.

With no synthesis model configured, research returns inspectable excerpts and gaps; ingestion pauses after structural publication. A fully indexed report is not automatically fully understood or regulatory evidence.

## Knowledge graph and ontology screens

The sidebar exposes **Knowledge graph** at `/knowledge-graph` and **Ontology** at `/ontology`.

Knowledge graph lets you choose a published finding, inspect an actual bounded Neo4j graph, expand from 50 to 100 nodes, zoom and fit, and select a relationship to inspect its kind, scope, review status, value and original source links. Selected relationships highlight their immediate neighbours. Traversal stays inside the pinned publication and cannot pass through a report hub into unrelated items. Connected sampling reserves room for assertions and source anchors so image-heavy reports do not hide the evidence. If Neo4j is unavailable the provenance preview is explicitly labelled.

Ontology shows the implemented catalog: 14 concepts, seven concept families, aliases, definitions, 17 permitted assertion predicates and evidence-passage counts from the active publication. A concept-family graph and searchable cards keep building, concrete-finish and membrane Class 2 senses separate. This is the implemented search vocabulary; the broader domain design in `ONTOLOGY.md` is not silently represented as executable regulatory rules.

## Live AI research

**Report drafting** is the default Research mode. Enter a short issue such as “water ingress from the bathroom”. A model first assesses the conversation and existing project facts. It asks up to three relevant follow-up questions when needed, accepts a free-text reply, and reassesses it. It can skip clarification when the initial request is adequate. There is no mandatory intake checklist; existing work versus proposed repair is asked only when material to the requested answer. Unknown details remain explicit rather than blocking an attributed provisional draft indefinitely.

The drafting graph then retrieves exact applicable original requirements when a reviewed applicability decision exists, searches report passages, reads complete published report sections, and optionally retrieves useful original images. An evidence grader can request further retrieval before drafting. The result is organised into observation/finding, requirements, technical assessment, opinion and recommendation, with numbered citations, exact quoted support and selected historical illustrations. Conversation, declarations, model/tool receipts and source versions are saved. Chat replies are durably queued and survive an API restart.

Current source coverage matters: this workspace has no reviewed original regulatory editions or active rule pack. A live draft can attribute the sample report's reasoning and cited standards, but cannot verify a governing BCA/NCC breach. Historical report approval for reuse is also unverified. The interface labels these gaps and retains technical review as a requirement. A separate verifier invocation may still use the same configured model family.

The research graph uses LangChain `ChatOpenAI` with the selected OpenAI-compatible endpoint. Its model-driven tool loop calls `StructuredTool.ainvoke` inside LangGraph. Available tools search passages, read exact sources, enumerate findings, read complete report sections, retrieve applicable original requirements, find original visuals by caption/OCR/context, and traverse Neo4j relationships. Model calls consume the active-time budget but not the research-tool counter; retrieval rounds and tool calls remain bounded. Each run retains model response metadata, token usage, tool arguments/results, its publication manifest and PostgreSQL checkpoints.

After retrieval, a model drafts structured claims with exact quotations and source anchors. Mechanical checks reject invented/out-of-scope citations and mismatched quotations. A separate model call checks support and qualifications before publication. The UI shows the workflow, claims, citations, gaps and call receipts. The verifier may use the same model in a separate invocation; this is not independent human expert review.

On this machine the private `.env` is configured as follows, with the API key retained only in that file:

```dotenv
TEXT_PROVIDER=fireworks
TEXT_ENDPOINT=https://api.fireworks.ai/inference/v1
TEXT_MODEL=accounts/fireworks/models/qwen3p8-max
VERIFIER_MODEL=accounts/fireworks/models/qwen3p8-max
FIREWORKS_API_KEY=<your-private-key>
EMBEDDING_PROVIDER=fireworks
EMBEDDING_MODEL=accounts/fireworks/models/qwen3-embedding-8b
EMBEDDING_DIMENSIONS=4096
ACTIVE_SECONDS=300
```

To switch the final app to OpenAI, use `TEXT_PROVIDER=openai`, `TEXT_ENDPOINT=https://api.openai.com/v1`, matching OpenAI synthesis/verifier model names, and `OPENAI_API_KEY` in `.env`. Select an OpenAI embedding model and rebuild its index. The LangChain/tool/graph code stays the same. Provider settings saved in the UI persist across API restarts and take precedence over `.env` selections; keys always come from the server environment. Restart after changing keys. A legacy custom compatible endpoint uses `PROVIDER_KEY`.

In Settings, **Save and test AI connection** makes a small real structured-output request. In Research, enter a question and click **Start research**, then inspect citations and the workflow. Model calls have a configurable `MODEL_TIMEOUT` (default 90 seconds), no automatic retries, and cumulative tool/time budgets. An unknown paid-request outcome requires a new explicit run; it is not silently replayed.

## Embedding providers

The Settings screen now offers local BGE, OpenAI `text-embedding-3-small` / `text-embedding-3-large`, and Fireworks Qwen3 Embedding 8B. Embeddings are independent of the synthesis/verifier provider. Add credentials to this folder's private `.env`, restart with `.\start-app.ps1 -Native -Restart`, choose a model under **Search embeddings**, save, and click **Rebuild search index**. Update the existing file rather than replacing its database credentials.

For OpenAI text embeddings:

```dotenv
OPENAI_API_KEY=your_openai_api_key
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

For Fireworks text embeddings:

```dotenv
FIREWORKS_API_KEY=your_fireworks_api_key
EMBEDDING_PROVIDER=fireworks
EMBEDDING_MODEL=accounts/fireworks/models/qwen3-embedding-8b
EMBEDDING_DIMENSIONS=4096
```

Settings saved in the workspace take precedence over these `.env` provider/model defaults; credentials are read only from the server environment/`.env`. OpenAI's large model defaults to 3072 dimensions. These hosted models also accept shorter vector dimensions. Every provider/model/dimension/query-format combination has a separate Qdrant collection and cache; keys are excluded from profile identities and browser responses. Fireworks Qwen queries use an instruction prefix and returned vectors are normalized before indexing.

The durable rebuild stages and validates every published document, then atomically changes the active manifest. A source-library change or failed provider response prevents publication. Existing manifests and original anchors remain available, and exact/keyword search works while a different embedding profile is awaiting rebuild. Completed embedding batches are cached. Requests have explicit timeouts, cumulative budgets and no SDK retries; an unknown interrupted request is not silently replayed. Queue another rebuild only after inspecting a failed attempt; it is an explicit retry and may incur another provider charge.

Hosted text embeddings send report text chunks and search queries to the selected destination, independently of whether synthesis is enabled. They never upload original files or image pixels. **The OpenAI and Qwen embedding options are text-only.** Configure image retrieval separately below; a vision chat model does not create a visual embedding index.

Provider contracts: [official OpenAI embedding documentation](https://developers.openai.com/api/docs/guides/embeddings) and [Fireworks embeddings documentation](https://docs.fireworks.ai/guides/querying-embeddings-models). Fireworks documents Qwen3 Embedding 8B as serverless; its smaller Qwen embedding models and Voyage multimodal models require dedicated deployments. No hosted request has been executed against company evidence during validation.

## Voyage multimodal image retrieval

Settings → **Image embeddings** adds Voyage Multimodal 3.5 independently of the text provider. The existing OpenAI/Qwen text options remain available.

For Fireworks, keep `FIREWORKS_API_KEY` in `.env` and enter a dedicated Voyage deployment path in Settings: `accounts/your-account/deployments/your-deployment`. The public Fireworks embedding reference documents the text endpoint and arbitrary structured inputs but does not specify a multimodal image example. The app's declared OpenAI-compatible image-content adapter must pass the **Test synthetic images** check against the actual deployment before any source pixels can be embedded. This adapter has been tested with mocked responses, not against a live Fireworks deployment.

Voyage's documented direct API is a separate selectable alternative using `VOYAGE_API_KEY` in `.env` and `https://api.voyageai.com/v1/multimodalembeddings`. The app never silently switches provider or credentials. Supported dimensions are 256, 512, 1024 and 2048 (default 1024); unsupported deployment dimensions fail validation.

1. Add the selected provider's key in `.env`, then restart with `.\start-app.ps1 -Native -Restart`.
2. Choose the visual provider and supply the Fireworks deployment path if applicable; save the visual settings.
3. Run **Test synthetic images**. Only two locally generated shapes and two text queries are sent. The test verifies dimensions, finite normalized vectors, response alignment and correct shape/text ranking. Passing it is a basic connection check, not construction-domain evaluation.
4. Enable **sending report images and captions**, save, then click **Rebuild image index**. The rebuild stages the text and visual projections and publishes them together only after validation.

Image indexing sends bounded PNG derivatives of embedded report images and up to 1500 Unicode code points of source caption/OCR/item context. Original DOCX/PDF files remain local, and original media bytes/anchors stay immutable. Images are limited to a 1600-pixel long edge and safe payload size. GIF/TIFF use the first frame/page; unsupported formats and oversized images are listed as skipped coverage, retain their original viewers and remain searchable through OCR/captions.

Qdrant visual collections and caches are separate from text embeddings and versioned by provider, deployment, dimensions, input formats and preprocessing. Image queries use the same Voyage profile's query embeddings. General image search combines visual similarity with OCR/caption/linked text; exact figure identifiers retain priority. Each hit is hydrated against the current manifest, original asset hash and source-context hash. Stale/mismatched hits are rejected; provider failure retains source/keyword access. Visual similarity finds candidate evidence and does not establish diagnosis, figure identity or regulatory applicability.

Optional `.env` defaults (saved Settings take precedence):

```dotenv
VISUAL_EMBEDDING_PROVIDER=disabled
VISUAL_EMBEDDING_DEPLOYMENT=
VISUAL_EMBEDDING_DIMENSIONS=1024
VISUAL_EMBEDDING_ENABLED=false
VOYAGE_API_KEY=
```

Provider references: [Fireworks Voyage model/deployment](https://fireworks.ai/models/fireworks/voyage-multimodal-3-5), [Voyage multimodal API](https://docs.voyageai.com/reference/multimodal-embeddings-api). Live keys/deployment access, Fireworks wire-format compatibility, provider billing/latency and construction-specific retrieval accuracy remain unverified.

## Fresh source installation

Install Python 3.12, uv, Node 22.12+ and pnpm 11.25.0. Windows validation used Python 3.12.14 and bundled Node 24.19.0. Container pins are in [compose.yaml](compose.yaml) and [Dockerfile](Dockerfile).

```powershell
uv sync --locked --extra models
uv run alembic upgrade head
uv run python scripts/setup_models.py --download --revision a5beb1e3e68b9ab74eb54cfd186867f64f240e1a
uv run python scripts/setup_docling.py
```

In `web/`, run `pnpm install --frozen-lockfile` and `pnpm build`.

Model setup explicitly downloads public artifacts only and never reads reports. BGE is frozen to the revision above; the actual tokenizer counts the whole input, with a 480-token hard limit. Docling layout/table artifacts and RapidOCR ONNX paths are local. Runtime parsing/embedding does not follow company document links or enable cloud tracing.

For the five-service container route, install Docker Desktop/Compose, copy `.env.example` to `.env`, and set `CONTAINER_BGE_PATH=/models/bge-base-en-v1.5/a5beb1e3e68b9ab74eb54cfd186867f64f240e1a` and `CONTAINER_DOCLING_PATH=/models/docling`. Then:

```powershell
.\start-app.ps1
```

The helper creates missing local service secrets. Compose defines API, worker, PostgreSQL, Neo4j and Qdrant with persistent volumes; only 127.0.0.1:8000 is published. Docker is absent here, so fresh container build/start/upgrade remains unexecuted. Native and container workspaces are separate; transfer by explicit verified backup, not a live SQLite copy.

Portable helpers expect official PostgreSQL 17.6, Neo4j Community 5.26.32, Qdrant 1.19.2 and Temurin Java 21 under `.tools/`. These are installed locally but are not source artifacts. `scripts/setup_native_postgres.ps1` and `scripts/setup_native_stores.ps1` configure authenticated loopback services. See the official [PostgreSQL Windows archive route](https://www.postgresql.org/download/windows/) and [Qdrant release](https://github.com/qdrant/qdrant/releases/tag/v1.19.2).

## Product routes

- **Library:** import DOCX/PDF files or a selected folder, choose role/family, inspect anchored blocks, retry/cancel jobs, open originals and archive a version from new research. Exact duplicates reuse their version. Reviewed same-version Word/PDF equivalence retains both anchors and avoids double-counting.
- **Findings:** search DS/location/item wording or hybrid candidates; inspect occurrence observations, labelled shared reasoning/status/result/responsibility and distinct repair options.
- **Evidence images:** exact figure/standard or descriptive search; original bytes, OCR provenance, Word/PDF locators and independent source-page/identity states.
- **Research:** historical/current/remedial/comparison modes; a model-driven LangChain tool loop in LangGraph, PostgreSQL checkpoints, persisted model/tool receipts, cumulative budgets, typed fact interrupts, structured synthesis and mechanical/model support checks. Saved evidence remains immutable and becomes stale after dependent changes.
- **Projects:** attributable facts in separate original/remedial contexts per building part. Missing/conflicting facts remain unresolved; a declaration is not verified approval evidence.
- **References:** reported citations/demands, reviewed original editions/fragments and scoped exact chains. A PDF upload cannot activate adoption coverage. Rules require original support, an explicit reviewer and executable passing fixtures; synthetic rules cannot activate real coverage.
- **Review:** inspect issues or assertions with source support, record audited successors, reject stale edits, and republish dependent immutable metadata/receipts.
- **Knowledge graph:** explore findings or any published domain record in Neo4j, inspect its class, source-qualified relationships and original passages/images. The finding route retains a labelled canonical preview when Neo4j is unavailable.
- **Ontology:** a draft shared schema containing class definitions, properties and relationship signatures. Report records and identifiers are browsed separately under Knowledge graph → Report records; search words have their own vocabulary view and SKOS graph. The draft is not a domain-validated ontology, and counts or passing software tests do not establish correctness.
- **Settings:** separate readiness/destinations, budgets and managed canonical backup/restore. Vision remains gated pending explicit capability validation.

For the private sample, try `Planter`, `DS-68`, or `AS 4654.2-2012 Figure 2.17`. The original figure links to planter item context and printed AS page 30. This identification does not establish applicability.

## Checks and development

```powershell
uv run pytest -q
uv run ruff check app scripts tests
uv run mypy app
```

Frontend: `pnpm test`, `pnpm build`, `pnpm generate:api`, and `pnpm test:e2e` in `web/`. Browser tests mutate an isolated synthetic workspace on port 8001 with installed Edge; do not point them at a company workspace. See [VALIDATION.md](VALIDATION.md) for executed environments and unexecuted gates.

`scripts/validate_private_fixture.py` audits original hashes/media, canonical spans, actual BGE counts, figure identity, citation resolution and one-report latency. Detailed private results stay in `data/qa/`. No 50-question held-out evaluation or ten-case manual-time comparison has been performed.

The default saver is PostgreSQL. `CHECKPOINT_BACKEND=sqlite-dev` is restricted to explicit isolated development/tests. Checkpoints reference canonical IDs; documents/chunks/assertions remain in SQLite. See [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) and [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

## Privacy, rights and recovery

Originals are immutable/content-addressed; access resolves managed IDs. Files, pixels, extracted content, credentials, service data, embeddings and QA artifacts are excluded by `.gitignore`/`.dockerignore`. The supplied original outside this folder remains unchanged. Provider secrets stay server-side; text configuration does not enable images. Hosted file search, arbitrary model SQL/Cypher, macros and document-requested actions are absent.

The implementation is independently written. Both demonstration repositories remain unchanged; no restricted source was reused. See [REUSE.md](REUSE.md). No application TTL files were authored; `knowledge/catalog/domain-model-v1.json` is the governed domain schema, with an in-memory OWL/RDFS projection. `scripts/build_domain_model.py` reproducibly compiles the schema and its section-coverage register from the reviewed design. `app/domain.py` creates immutable, source-qualified report snapshots, validates type/source/status constraints and projects instance-to-class links into Neo4j. A publication manifest selects the snapshots, graph and vector revisions together; staged or historical versions do not inflate current counts.

The report graph currently represents document evidence and unreviewed automatic mappings. It retains report identifiers, source passages, responsibility statements, repair scopes, cited references and images. Report headings cannot create physical building elements; explicit identification evidence is required. The schema is unchanged by importing reports, and the same finding number in two reports identifies two separately scoped records. Correct physical-entity, defect and assessment interpretation across diverse reports still requires semantic redesign and domain validation; this is an outstanding implementation requirement.

Canonical backups retain a consistent SQLite snapshot, immutable assets, catalog/rules and run evidence with checksums. Restore verifies bounds/integrity and preserves a recovery snapshot. Backups include a quiesced PostgreSQL workflow dump when PostgreSQL is configured. Restore validates canonical/checkpoint references and stages verified graph/vector rebuilds before activation; incompatible or unfinished work remains interrupted for explicit refresh. A pre-restore recovery snapshot is retained.

Design contracts remain [PRD.md](PRD.md), [SPEC.md](SPEC.md), [DATA_PIPELINE.md](DATA_PIPELINE.md), [ONTOLOGY.md](ONTOLOGY.md), [TASKS.md](TASKS.md) and [ACCEPTANCE_TESTS.md](ACCEPTANCE_TESTS.md). Their complete release gates exceed this pilot's executed evidence.
