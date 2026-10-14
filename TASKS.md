# Defect Intelligence Implementation Tasks

Version 2.0  
Date 12 October 2026  
Status Planned implementation backlog  
Product scope [PRD.md](PRD.md)  
System design [SPEC.md](SPEC.md)  
Domain model [ONTOLOGY.md](ONTOLOGY.md)  
Data contracts [DATA_PIPELINE.md](DATA_PIPELINE.md)

## Objective and delivery order

Build one local application that turns company Word/PDF expert reports into connected, searchable defect knowledge and returns evidence-backed research with original images and context-specific code/standard decisions.

The tasks below are implementation work. Their presence does not mean their code or tests have been completed. The current folder contains design documents; executable modules and dependency files are task outputs. No task in this baseline requires writing TTL files: the operational ontology uses reviewed JSON/canonical records and an in-memory RDF projection. TTL authoring requires a subsequent explicit user instruction.

The implementation order is:

1. Establish representative fixtures, source coverage and a compatible locked technology stack.
2. Preserve documents/images and build restartable ingestion with exact source locations.
3. Extract the domain model and publish consistent graph, lexical and semantic projections.
4. Build original-reference chains, reviewed rules and building/work applicability contexts.
5. Complete the LangGraph research workflow, verification and all product screens.
6. Evaluate, recover, benchmark and package the accepted local release.

Use task IDs when tracking work. A task is complete only when its outputs exist and its completion checks pass. Record dependencies, actual results and relevant source/test versions; do not mark a task complete based on a generated answer or screenshot alone.

## M0 Product corpus and executable stack baseline

| Task | Dependencies | Implementation output | Completion check |
|---|---|---|---|
| T01 Stack compatibility and locks | None | Verify Python/Node, LangGraph/LangChain Core, PostgreSQL saver, Docling/RapidOCR, embedding tokenizer/dimension, PDF.js and store clients. Produce lockfiles and image/model/graph release manifest. | A standalone structured extraction/store/viewer/checkpoint spike runs on the pilot machine; exact compatible versions are recorded, with no latest tags or silent truncation. |
| T02 Pilot evidence and expected results | None | Inventory sample/representative DOCX, native/scanned PDFs, code/AS editions and project facts. Create reviewed extraction/relationship fixtures, at least 50 held-out research questions and ten manual-time baseline cases. | Expected image/anchor/occurrence mappings and applicability outcomes have named sources/reviewer; held-out questions are separated from tuning fixtures. |
| T03 Source reuse and coverage route | None | Record source-code reuse rights, independently written module route where needed, supplied reference access and first jurisdiction/edition/class coverage. | Neither restricted demo is copied without rights. Initial covered scope and missing sources are explicit; the computer timezone is not a jurisdiction input. |
| T04 Application scaffold and provider ports | T01, T03 | Backend API/worker, React app, five Compose services including PostgreSQL, registered LangGraph builders, migrations/settings and provider ports with test doubles. | Health/UI start; a synthetic StateGraph executes; services/model/checkpoint readiness are distinct; unconfigured transmissions are disabled. |

M0 exits with an executable skeleton, validated component baseline and reviewed pilot scope. It is not yet a usable defect research application.

## M1 Source library and visual ingestion

| Task | Dependencies | Implementation output | Completion check |
|---|---|---|---|
| T05 Canonical schema and identity | T02, T04 | Alembic migrations and repositories for sources/assets/anchors, domain assertions, references, jobs, projections, contexts and runs. Ownership constraints and query indexes. | Fresh install/upgrade works; invalid ownership and duplicate identity cases fail/reuse correctly; original identifiers remain preserved. TC04–TC07. |
| T43 Physical structure contracts and persistence | T02, T05 | DocumentIR/SourceBlock/Locator schemas, ordered tree/table/cell/media storage, physical versus semantic revisions and validated IR assets. | DOCX/PDF adapters can persist mixed/nested blocks and exact locators; Unicode/rotation/ownership fixtures pass. TC55. |
| T48 LangGraph persistence and replay infrastructure | T04, T05 | AsyncPostgresSaver lifespan/setup, registered graph/schema versions, thread IDs, durable budget/operation ledger and checkpoint/artifact reconciliation. | A synthetic workflow resumes after restart/interrupt without duplicate side effects, graph-version mixing or reset budgets. TC61, TC62. |
| T06 Managed assets and upload/version service | T05 | Bounded uploads, hashing, immutable file storage, media role/version/rendition records and managed preview access. | Exact duplicates do not inflate findings; revisions/renditions stay distinguishable; over-limit/invalid/out-of-scope input is rejected without damage. TC01, TC04–TC07, OP06, OP07. |
| T07 Durable jobs and events | T05, T06, T48 | SQLite admission/leases/outbox and LangGraph ingestion transitions; bounded shared retries/cancel and persisted SSE. | Queue and graph have distinct ownership; lost leases safely resume compatible checkpoints/artifacts. OP01, OP02, TC61. |
| T08 Word and legacy adapters | T06, T07, T43 | Ordered OOXML paragraphs/tables/lists/drawings into DocumentIR, exact locators, original media and occurrences; optional converter. | Sample media inventory and mixed/nested structure survive, including image-only extracts; Word pages are not invented. TC01, TC03, TC07, TC37, TC55. |
| T09 PDF and region adapters | T06, T07, T43 | Docling JSON/provenance into DocumentIR, reading order, cells and PDFium region renders with raw/normalized bounds. | Native/scanned/rotated fixtures preserve source coordinates, table structure and separate printed locators. TC01, TC02, TC07, TC39, TC55. |
| T10 OCR and visual extraction | T08, T09 | RapidOCR region text/confidence, table layout, image-role/source candidates and attributable optional diagram descriptions. | Image-only BCA/AS wording is searchable; uncertain numbers/years and cropped notes are flagged; image processing honours destination settings. TC37, TC39, TC40, TC48. |
| T11 Source and image viewer foundation | T06, T08, T09 | PDF.js overlays, safe anchored Word blocks, image zoom/original access and source identity/context panels. | A source anchor opens the correct version/location; original image, caption and report/source locators are readable. TC07, TC08, TC38, OP06. |
| T12 Library and import UI | T07, T11 | File/folder import, role/version controls, job progress/retry/cancel, ready/partial/configuration/error states and document inspection. | The user imports and inspects a representative report through the UI while previously published sources remain usable. F01, OP08. |

M1 exits with preserved, inspectable text and visual sources plus resumable processing. Domain associations and governing decisions are still under construction.

## M2 Connected domain knowledge and search

| Task | Dependencies | Implementation output | Completion check |
|---|---|---|---|
| T13 Operational ontology catalog | T02, T05 | Governed JSON definitions/aliases, distinct building/concrete/membrane classes, canonical concept tables and curated in-memory rdflib/SPARQL queries. | Ambiguous aliases remain candidates, concept/version/source links resolve and no TTL authoring is required. TC12, TC13, TC44. |
| T14 Typed domain extraction and grounding | T04, T08, T09, T10, T13 | Typed entity mentions/assertion candidates from logical section context, with exact source ranges, allowed predicates, scope and attribution. | Fabricated/foreign spans and unsupported claims fail; observation/history/opinion/inference stay distinct. TC09–TC11, TC15, TC29, TC58, TC59. |
| T15 Report hierarchy and shared scope | T14 | Item/occurrence segmentation, DS/location resolution, interfaces/consequences and explicitly scoped shared assessment/remediation links. | Multiple occurrences remain distinct, duplicate DS collisions and absent attachments create review items, and shared text is not assigned to every defect. TC09, TC45. |
| T46 Ontology mention and instance mapping | T13–T15, T43 | Governed catalog resolution, scoped entity matching, source-supported concept/entity/assertion links and new-term review queue. | No per-chunk ontology generation, global name/DS merges or class-family confusion; mappings retain version/support/status. TC58, TC60. |
| T44 Structure-aware parent and child chunker | T08–T10, T15, T43 | Full parent contexts and content-specific child packing, BGE tokenizer/offset mapping, bounded overlap and table/figure/option dependencies. | Complete eligible source coverage and <=480-token inputs; no cross-occurrence/option/type merges or lost headers/conditions. TC56. |
| T45 Canonical metadata and projections | T13–T15, T44, T46 | ChunkRevision/Segment metadata schemas, normalized semantic links, text/metadata/profile hashes, LangChain Document adapters and consistent payload/FTS receipts. | Metadata is canonical/versioned, citation years and governing context remain distinct, and correction/profile rebuild checks pass. TC57, TC63. |
| T16 Review and corrections service | T05, T14, T15 | Review queue, candidate evidence display, audited successor assertions and optimistic correction API. | A correction preserves history/support and schedules dependent updates; stale review versions cannot overwrite each other. TC11, TC30, TC52. |
| T47 Canonical graph construction batches | T14, T15, T45, T46 | Validated source/domain/concept/assertion/reference/repair/chunk projection rows, scoped identity rules and source-grounding receipts. | Every factual relation has valid typed endpoints/support; reported citations do not become adoption edges; no similarity-created facts. TC59, TC60. |
| T17 Neo4j projection and templates | T13–T16, T47 | Node/assertion constraints, parameterized incremental MERGE, bounded traversals and provenance output. | All projected IDs match canonical construction receipts; no full graph deletion or model-generated Cypher exists. TC14, TC15, TC59, OP02. |
| T18 FTS and exact identifiers | T05, T10, T15, T45 | Persistent canonical-revision FTS, captions/OCR/descriptions and normalized exact identifiers. | Exact/alias matches keep content/source kinds and manifest scope; uncertain OCR is not silently repaired. TC16, TC23, TC37, TC40, TC57. |
| T19 Local embeddings and Qdrant | T01, T15, T44, T45 | Frozen BGE tokenizer/model/profile, embedding cache, 768-dimensional collections, indexed payload fields and revision writes. | Input limits/profile hashes match chunk records; text changes re-embed and metadata-only changes republish consistently. TC16, TC56, TC63, OP03. |
| T20 Consistent publication manifests | T07, T17–T19 | Staged projection receipts, immutable manifest membership, atomic activation and revision-scoped reads/reconciliation. | A failed store write leaves the old manifest usable; concurrent research cannot mix projection revisions. OP01, OP02, TC30. |
| T21 Hybrid and graph retrieval | T13, T17–T20 | Exact lookup, BM25/vector RRF, report diversity, graph source expansion and structured all-occurrences pagination. | Exact/paraphrase queries retrieve expected findings, historical edition differences are preserved, and enumeration is complete or explicitly limited. TC16, TC17, TC35. |
| T22 Visual evidence retrieval | T10, T11, T20, T21 | Exact/OCR/semantic/graph image search with occurrence/context, preserved original assets and source identification states. | Exact and natural-language Figure 2.17 queries return the sample's original figure/related reasoning; shared image occurrences remain distinct. TC38–TC41. |
| T23 Findings search and graph UI | T11, T16, T17, T21, T22 | Filters/results, item/occurrence detail, visual results, remediation comparison and Cytoscape provenance/expansion panel. | The user follows a retrieved occurrence through reasoning, sources/images and distinct repair alternatives. No unbounded graph or image-gallery load. F02–F04, F09, F12, OP08. |

M2 exits with useful historical research/search and inspectable source-backed relationships. Applicability coverage remains explicit and incomplete until M3.

## M3 Versioned requirements and applicability

| Task | Dependencies | Implementation output | Completion check |
|---|---|---|---|
| T24 Original reference catalog | T08–T10, T13, T20 | Code volume/year/amendment and AS family/part/year/amendment identities; clause/table/figure/definition hierarchy and complete-context anchors. | Same-number fragments in different editions remain distinct and source roles/notes/conditions are preserved. TC22, TC23, TC39. |
| T25 Citation resolution and source demands | T14, T22, T24 | Visible/inferred/unknown image identification, reported citation candidates, original-source matching and missing edition/fragment register. | Mixed years and cropped headers remain attributable; adding a needed original extends coverage without rewriting historical citations. TC40, TC43, TC47. |
| T26 Reviewed typed rule engine | T02, T05, T13, T24 | JSON rule packs, typed predicates, true/false/unknown evaluation, source/fixture activation checks and conflicting-rule detection. | Missing facts yield unknown, inactive/unsupported rules cannot authorize decisions, and reviewed exception/transition fixtures pass. TC18–TC20, TC31. |
| T27 Building-part classification | T13, T15, T26 | Recorded/derived classifications from versioned definitions and source-backed use/configuration facts, with explicit alternatives and dependencies. | Mixed-use and unresolved classification cases pass; concrete finish or membrane class cannot become building class. TC13, TC21, TC44. |
| T28 Edition and reference-chain decisions | T24–T27 | Jurisdiction/work edition/volume decisions and scoped primary/secondary/project reference evaluation with exact AS parts/amendments. | No newest/nearest/earlier-year heuristic; rule-specific exceptions and original-source gaps produce expected decisions. TC18–TC24, TC42, TC43. |
| T29 Work events and remediation contexts | T15, T26–T28 | Original/later/proposed work packages, repair history, separate context versions and alternative scopes/prerequisites. | A failed repair stays a documented work event; original and remedial assessments remain separate. TC25, TC36, TC46. |
| T30 Context, reference and coverage UI | T16, T24–T29 | Building-part fact editor, decision rationale, reference chains, rule review/coverage and source-demand screens. | The user can identify a missing fact/source, inspect its impact and supply/review evidence; uploading a PDF alone cannot activate a governing decision. F06–F08, F13, TC31, TC47. |

M3 exits with critical reviewed classification/edition/reference-chain fixtures passing for the declared pilot scope. Other jurisdictions, years and classes remain visible gaps rather than implied coverage.

## M4 Complete research workflow

| Task | Dependencies | Implementation output | Completion check |
|---|---|---|---|
| T31 LangGraph research workflow | T04, T21, T22, T28, T29, T48 | StateGraph schema/nodes, explicit conditional edges, tool registry and context/manifest/checkpoint versions. | Typed retrieval/verification gates, missing-fact interrupts and durable budgets work; no parallel bespoke agent controller. TC26, TC49, TC61, TC62. |
| T32 Typed tools and evidence bundles | T17, T21, T22, T28, T31 | Permissioned registry for context/rules/search/graph/exact-source/media/enumeration tools, with service/coverage states. | Unknown IDs, unavailable stores and document instructions cannot expand permissions or produce invented evidence. TC15, TC27, TC34, OP04. |
| T33 Claim synthesis and verification | T04, T28, T31, T32 | Typed answer claims, mechanical source/context/edition checks and separate model review using full required context. | Fabricated anchors and wrong-year/class claims are rejected despite favourable model output; qualified opinions and unsupported sections stay distinct. TC27–TC29, TC39, TC42. |
| T34 Research workspace and live progress | T11, T30–T33 | Question/mode/context controls, persisted SSE progress, answer/evidence panel, targeted clarification and cancellation. | A complete planter research journey works through the UI, including original figure retrieval and unresolved context where applicable. F05, F10, TC26, TC38. |
| T35 Saved runs and dependency invalidation | T16, T20, T29, T33, T34 | Initial/final context snapshots, LangGraph thread/checkpoint lineage, stale tracking and continued-question new runs. | Corrections/version changes preserve old evidence and reject unsafe state reuse; compatible interrupted workflows resume within their budget. TC30, TC32, TC51, TC53, TC61–TC63. |
| T36 Settings, health and recovery features | T04, T07, T20, T35 | Redacted provider/budget settings, capability tests, explicit image destinations, service readiness and managed backup/restore jobs. | Secrets remain server-side, disabled image processing makes no implicit pixel requests, and backups record source/catalog/rule/model/manifest versions. TC33, TC48, TC50, TC54, OP04–OP06. |
| T37 Product integration and review | T12, T23, T30, T34–T36 | All fifteen first-release features connected through routes, shared source viewer and consistent statuses. | A user completes historical, current-building, remedial, comparison, review/correction and saved-run journeys without switching between demo apps. |

M4 exits with all P0 features implemented. Quality, capacity and operational acceptance still determine release readiness.

## M5 Accepted local release

| Task | Dependencies | Implementation output | Completion check |
|---|---|---|---|
| T38 Held-out quality evaluation | T02, T37 | Extraction/retrieval/graph/applicability/claim metrics, reviewed failures and fixes, business-time comparison. | At least 50 held-out questions and all critical fixtures satisfy PRD targets; no accepted wrong-class/edition governing claim in the release suite. |
| T39 Capacity and contention benchmark | T01, T37 | Recorded hardware/corpus profile, media-heavy import plus concurrent query, search/agent latency and memory results. | Meet declared pilot limits or revise measured limits visibly; ingestion cannot starve research or silently drop source context. |
| T40 Restart and recovery verification | T07, T20, T35, T36, T48 | Interrupted graphs/jobs/publication/provider cases, canonical/checkpoint backup reconciliation and index rebuild. | OP01–OP05 and TC61–TC63 pass; restored checkpoint/artifact/context IDs agree and replay duplicates no counted findings. |
| T41 UI and boundary validation | T37 | Playwright user journeys, keyboard/narrow-layout checks, managed asset access and untrusted-content fixtures. | OP06–OP08 and required product journeys pass; loading/partial/unavailable/stale states remain usable and clear. |
| T42 Local release packaging | T01, T03, T38–T41 | Locked images/builds, start-app.ps1, setup/backup instructions, release manifest and acceptance result record. | A fresh local install starts without destructive demo seeding; upgrade retains data; all release gates in ACCEPTANCE_TESTS.md are recorded as passed. |

## Dependencies and critical path

```mermaid
flowchart LR
  M0[M0 Fixtures and locked stack] --> M1[M1 Sources and visual ingestion]
  M1 --> M2[M2 Domain graph and hybrid search]
  M2 --> M3[M3 Reviewed applicability]
  M3 --> M4[M4 Complete research workflow]
  M4 --> M5[M5 Evaluation and local release]
```

Within a milestone, follow each task's dependencies. Ranges such as T17–T19 mean all listed tasks in that range. An implementation may overlap independent work, but cannot claim a milestone complete while its source, rule or publication prerequisites are missing.

The critical path is source identity and extraction -> domain associations -> consistent search/graph publication -> reviewed reference/applicability coverage -> verified research -> release evaluation. Frontend progress alone cannot bypass that path.

## Feature completion map

| Product features | Main tasks | Release evidence |
|---|---|---|
| F01 Import/library | T05–T12 | TC01–TC08, TC37, OP01, OP02, OP07 |
| F02/F03 Connected findings/search | T13–T21, T23 | TC09–TC17, TC35, TC44, TC45 |
| F04 Visual search | T10, T11, T22, T25 | TC37–TC41, TC47, TC48 |
| F05 Research assistant | T31–T34 | TC26–TC29, TC34, TC49 |
| F06/F07 Context/classification/code | T26–T30 | TC10, TC11, TC13, TC18–TC21, TC24, TC36, TC44 |
| F08/F13 References/coverage | T24–T28, T30 | TC22, TC23, TC31, TC42, TC43, TC47 |
| F09 Reasoning/remediation comparison | T15, T23, T29, T33 | TC25, TC29, TC36, TC46 |
| F10 Source viewer | T11, T22, T34 | TC07, TC08, TC38–TC40, OP06 |
| F11 Review | T16, T25, T30, T35 | TC11, TC30, TC40, TC43, TC45, TC52 |
| F12 Graph explorer | T17, T23 | TC14, TC15, OP04, OP08 |
| F14 Saved research | T35 | TC30, TC32, TC51, TC53, OP05 |
| F15 Settings/health/recovery | T04, T36, T39–T42 | TC32, TC33, TC48, TC50, TC54, OP01–OP08 |

## Data pipeline completion map

| Contract | Tasks | Acceptance |
|---|---|---|
| Document tree, source locators and storage | T43, T08, T09 | TC55 |
| Parent/child chunking and exact coverage | T44, T19 | TC56 |
| Canonical metadata and payload ownership | T45, T18–T20 | TC57, TC63 |
| Global ontology and scoped instance mapping | T46, T13–T15 | TC58, TC60 |
| Qualified knowledge graph construction | T47, T17 | TC59, TC60 |
| LangGraph checkpoints/interrupts/replay | T48, T07, T31, T35, T40 | TC61, TC62 |
| Sample report to exact figure/evidence query | T08–T10, T21–T23, T31–T34 | TC64 |

Task IDs are stable; the six additional contracts are positioned in their dependency milestones rather than renumbering earlier work. The backlog contains 48 tasks. DATA_PIPELINE.md and SPEC.md govern their shared schemas and node/store ownership.

## Definition of complete

Each task's completion record includes its code/artifact paths, schema/parser/model/catalog revisions, fixture IDs, expected versus actual results, material limitations and date. Source extraction and deterministic guards need reproducible fixtures; visual UI work needs interaction and rendered checks.

The release requires all first-release features, all P0 product scenarios and operational checks, the PRD quality/performance targets, usable original evidence and explicit supported reference/rule coverage. All source/code rights must be established for the selected implementation route.

If a governing source or reviewed rule is unavailable, implement and verify the unresolved behaviour and declare the affected scope. Do not mark that scope supported by substituting model memory or report citations. A functional historical-research path can still pass its own checks.

## Work requiring further input during implementation

The initial corpus beyond the supplied sample, original AS/code documents, review of jurisdiction/definition rules, provider credentials/destinations and source-code reuse rights are implementation inputs. Record them as specific source/configuration/review tasks rather than using them to defer unrelated development. Do not request these again if already supplied.

TTL serialization is a separate future format decision requiring explicit user instruction. The baseline above implements the ontology and graph through the governed catalog and canonical source-backed records.
