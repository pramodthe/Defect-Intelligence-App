# Defect Intelligence Product Requirements

Version 3.0  
Date 12 October 2026  
Status Product definition and release requirements  
System design [SPEC.md](SPEC.md)  
Implementation backlog [TASKS.md](TASKS.md)

## Navigation

- [Main problem](#main-problem-we-are-solving), [product goals](#product-goals-and-intended-outcome) and [how the product works](#how-the-product-works).
- [First-release features](#features-in-the-first-complete-release), [research modes](#research-modes) and [user journeys](#main-user-journey).
- [Answer contents](#required-answer-contents), [functional requirements](#functional-requirements) and [user interface](#user-interface).
- [Release targets](#release-targets), [delivery stages](#delivery-stages) and [implementation tasks](TASKS.md).

## Product definition

Defect Intelligence turns the company's previous Word and PDF expert reports into a searchable, connected evidence library for building-defect research. The user describes an issue, finds comparable assessments, reads why the expert considered the work defective, examines the cited code/standard text and images, and compares the remediation proposed.

For questions about a current building or work package, the application must explain which requirements are applicable. It must use a building ontology, a graph of source-backed facts and a versioned reference library to resolve building classifications, BCA/NCC editions, clause scope and referenced standard editions. Hybrid document search supplies relevant passages and exact identifiers. The agent coordinates these capabilities and verifies the resulting answer.

Graph retrieval and ontology are mandatory product capabilities. The first complete release must include them together with hybrid search and applicability checks.

The primary product output is a **research answer with inspectable evidence**: relevant defect occurrences, observations, authored reasoning, attributed repair options, exact source extracts and images, and a transparent classification/code/reference decision where supported. Each answer remains saved with the sources and context used to produce it.

## Main problem we are solving

The company already has technical knowledge in its previous reports, but reusing it requires finding the right document and manually rebuilding its reasoning. Searching for waterproofing may find a paragraph without the associated site photographs, relevant AS diagram, approval context or repair limitations. A colleague's expertise can remain effectively hidden inside a report.

The supplied sample demonstrates this structure. A defect item can contain several DS occurrences at different units or levels, then separate sections for occurrence, status, result, reasoning, responsibility and remediation. References and drawings are frequently embedded as images. A text-only search can therefore miss the source that explains a conclusion, while a paragraph-only answer can lose which occurrence or repair option it belongs to.

The work also depends on regulatory context. A useful previous defect may concern another building part/class, code volume, BCA year, AS part/year, amendment or compliance pathway. Copying its clause or repair without examining those differences can produce an unsupported answer for the current job.

The product solves five connected problems:

| Problem | Product response | Observable benefit |
|---|---|---|
| Finding a relevant precedent takes manual report-by-report reading. | Search wording, aliases, exact references and governed defect concepts across the library. | The user can find comparable occurrences and their original report contexts. |
| Observations, reasoning, references and repairs are separated. | Preserve report structure and connect them in the evidence graph. | The user can follow the assessment from observation to conclusion and remedy. |
| BCA/AS extracts and drawings exist only as snapshots. | Preserve originals, OCR text and table layout, identify source fragments and index diagram descriptions. | Images can be found and displayed with their associated reasoning. |
| The right requirement depends on the building and work context. | Evaluate building-part classification, jurisdiction, approval/work evidence and exact reference chains. | The answer shows which requirement is supported and why, or the fact/source still needed. |
| Previous reports can contain uncertainties or inconsistent citations. | Keep source statements, review status and conflicting evidence visible. | The user can distinguish a faithfully retrieved opinion from a verified requirement. |

The source model is described in [ONTOLOGY.md](ONTOLOGY.md), using examples from the [sample expert report](../sample%20expert%20report.docx).

## Product goals and intended outcome

The main goal is to make the company's previous assessments reusable without losing their technical reasoning, source context or limitations. The user should be able to move from a described issue to an evidence-backed research bundle in one workspace.

The application must preserve these connections and make them searchable. A successful answer lets the user inspect both the historical precedent and the evidence supporting applicability to the current question. It must explain uncertainty at the affected claim, while still returning the supported research.

Product goals are to reduce repeated manual research, improve traceability of reasoning and requirements, retrieve visual source material, and prevent unsupported transfers of clauses or repair scopes between projects. Model fluency alone is not a success measure.

For pilot validation, record the user's time for ten representative manual research questions and compare it with accepted application answers to the same question types. Target a median reduction of at least 50% while meeting the evidence and applicability release gates. This is a proposed business target, not a measured result.

## Primary user

The initial user is a company building consultant or defects investigator. The same person may import reports, review extracted facts, maintain the reference library and assess the research output.

That person has three working roles: researcher when finding precedents, reviewer when checking extracted relationships and applicability, and library maintainer when adding reports or original references. The first release supports these roles within one local user workspace; multi-user permissions are a later product decision.

The application supports the user's investigation and judgement. It does not sign an expert opinion, certify compliance or automatically alter a company report.

## User specified scope

The following requirements come directly from the requested use case:

- Previous company reports in Word and PDF are the main inputs.
- Find defects, reasoning, remediation, clauses and sources.
- Use graph retrieval, an ontology and hybrid search together.
- Establish the correct BCA/NCC version, building classifications and applicable clauses where the available evidence supports that conclusion.
- Retrieve embedded BCA/AS screenshots, clauses, tables and figures alongside the associated defect reasoning and original visual evidence.
- Preserve code year, volume and amendments, and the exact referenced AS part, year and amendments.
- Deliver one usable application rather than separate demonstrations.

No user-prepared CSV is required. The application creates structured records from the documents.

## How the product works

The product has a preparation workflow and a research workflow. Importing reports establishes the evidence library; asking a question then uses that library and the current project's context.

~~~text
PREPARE
Import Word/PDF reports and reference documents
  -> preserve originals, images and source locations
  -> extract defect items, occurrences, reasoning and repair options
  -> identify concepts, references and relationships
  -> review uncertain links and publish searchable knowledge

RESEARCH
Describe an issue or search an exact clause/figure
  -> interpret terms and choose historical/current/remedial mode
  -> resolve relevant project facts when applicability is requested
  -> combine semantic search, keyword search and graph traversal
  -> retrieve original passages, snapshots, tables and figures
  -> check missing evidence, versions and contradictory information
  -> return a sourced answer with supported or unresolved sections
~~~

The ontology supplies shared meanings, such as the distinction between a building class and a concrete finish class. The graph supplies source-backed connections between an occurrence, its observations, reasoning, cited requirement and remediation. Hybrid search finds relevant wording even when the user's description differs from the report. The agent coordinates these capabilities, follows missing-evidence leads and verifies the final claims.

The selected agent framework is LangGraph. It manages the ingestion/research workflows, persisted execution and typed pauses for missing project facts. Framework checkpoints are workflow state; the company's documents, entities and evidence remain in the canonical library.

Document preparation retains a structured tree and full assessment/requirement units before creating small searchable chunks. Chunks carry exact source spans and supported links to the shared ontology/domain records. Selecting a result retrieves its complete relevant parent context, images and graph-linked evidence, so a small embedding window does not become the whole expert assessment.

Rules and reference coverage establish applicability. The model cannot decide that the newest BCA or an older-than-BCA AS edition applies just because that document is searchable.

Without a configured synthesis model, the user can still browse imported sources, search published findings and images, inspect graph evidence and review coverage. The research workspace explains that automated synthesis is unavailable. Model-assisted ingestion stages that cannot run retain a resumable needs-configuration status rather than pretending the report has been fully understood.

## Inputs and knowledge sources

| Source group | Accepted content | Purpose |
|---|---|---|
| Company report library | DOCX, text PDFs and scanned PDFs, including embedded photographs, BCA/AS snapshots, tables, figures, drawings and certificates; legacy DOC through a configured conversion adapter. | Historical defect items and occurrences, observations, reasoning, recommendations, visual evidence and citations. |
| Project evidence | Reports, approval documents, classifications, drawings or specifications supplied as Word/PDF, and explicitly recorded user declarations. | Jurisdiction, use, building parts, approval context, work scope and compliance pathway. |
| Reference library | Original BCA/NCC editions, amendments, jurisdiction provisions, supplied standards, specifications and manufacturer documents. | Verify exact requirements and their source versions. |
| Reviewed domain knowledge | Building concepts, defect terminology, applicability rules and source-supported mappings. | Interpret terms and execute applicability checks. |

A report's reference to a standard is useful even when the original standard is unavailable. The application must show that reference as reported, without presenting unavailable original text as verified.

Build the original reference library from editions required by the pilot reports and projects, then expand coverage as needed. Every historical BCA/NCC edition is not an initial upload requirement. Register missing originals, parts, amendments and source fragments discovered in report text and images, and keep historical report research available while those gaps remain.

The [domain ontology](ONTOLOGY.md) defines building class separately from concrete finish and membrane classes. It also distinguishes report defect items from their individual occurrences, observed consequences from predicted effects, authored responsibility from physical causation, and repair history from proposed remediation.

## Features in the first complete release

| Feature | What the user can do | Result | Requirements |
|---|---|---|---|
| F01 Report and reference import | Select Word/PDF files or a folder, identify source type and watch resumable processing. | Preserved originals, duplicate/version handling and per-file warnings/status. | FR01–FR03 |
| F02 Connected defect records | Open a defect item and its individual DS/location occurrences. | Observations, status, consequences, reasoning, responsibility and repair links remain inspectable. | FR04, FR07 |
| F03 Findings search | Search a description, defect alias, exact reference, element, unit or DS identifier. Filter by known metadata. | Comparable findings with match reasons and original contexts. | FR06, FR08, FR18 |
| F04 Evidence image search | Search an AS/BCA clause/figure identifier or describe a diagram detail. | Original snapshots, tables, drawings and photographs with captions, context and uncertainty. | FR03, FR22 |
| F05 Research assistant | Ask a question in historical, current-building, remedial or comparison mode. Follow evidence links and cancel a run. | Verified structured research answer, targeted clarification or scoped partial result. | FR13, FR14, FR17 |
| F06 Project context workspace | Create a project, identify buildings/parts and inspect or supply use, class, jurisdiction and approval/work facts. | Source-linked, versioned context with conflicts and missing facts visible. | FR05, FR06, FR19 |
| F07 Building and code assessment | Ask which class, code edition/volume and provisions are supported for the selected building part and work. | Decision rationale, rule/fact sources and supported/excluded/unresolved status. | FR09–FR11 |
| F08 Standards and reference chains | Inspect the exact AS part/year/amendments and its primary/secondary or project-specification reference basis. | Traceable code-to-standard-to-fragment relationship with scope and verification status. | FR10, FR16 |
| F09 Reasoning and remediation comparison | Compare previous assessments and repair options, including prerequisites and later repair history. | Attributed differences and alternatives without combining incompatible scopes. | FR12, FR19 |
| F10 Source viewer | Open a cited PDF page or Word paragraph/table; zoom an embedded image and inspect complete reference context where available. | Direct access to the original evidence, with separate report and printed source locators. | FR03, FR10, FR14, FR22 |
| F11 Review queue | Review uncertain OCR, identity, finding associations, classification or conflicting citations. Add a correction with a reason. | Audited revisions; affected projections update and saved answers show stale status. | FR15 |
| F12 Evidence graph explorer | Follow a finding's bounded graph and select an edge/node. | The source and status behind the relationship, with further expansion on demand. | FR07 |
| F13 Reference coverage and demand register | View available editions and missing documents/fragments; import a needed source. | Progressive coverage growth and explicit gaps instead of an all-editions prerequisite. | FR16 |
| F14 Saved research and run history | Reopen previous questions, answers, evidence bundles and context snapshots. | Reproducible research with stale indicators and a new run when continued. | FR14, FR17 |
| F15 Settings and workspace health | Configure models/destinations and budgets, inspect service readiness and run backup/restore operations. | Visible processing destinations, degraded-state guidance and recoverable local knowledge. | FR17, operational requirements |

All fifteen features above are part of the first complete release. Earlier development milestones expose subsets for validation but do not constitute the full product.

### Later features

P1 includes user-initiated exports of selected research into editable notes, advanced interpretation of new site photographs, broader corpus synthesis, additional reviewed jurisdiction packs and multi-user/deployment extensions if requested. These do not replace the P0 ability to retrieve existing images and source-linked diagram descriptions.

## Research modes

### Historical precedent research

Example question: "Find previous balcony waterproofing defects and show the reasoning and remediation used."

The application searches across previous report contexts. It returns relevant findings with their original building classifications and cited editions where recorded. A current project is optional. Different historical editions do not exclude a report from being a useful precedent.

### Application to a building or work package

Example question: "Which clauses apply to this defect in this part of our building, and which previous findings are comparable?"

The application resolves the relevant project facts and classification, then applies reviewed jurisdiction and edition rules. It retrieves original clauses and explains the decision. Missing facts produce a specific applicability question or an unresolved section; historical research can still be returned.

### Proposed remedial work

Example question: "What repairs were recommended previously, and what requirements need checking for this proposed remedial work?"

The application retrieves previous recommendations and their limitations. It establishes a separate context for the proposed work. It must not automatically carry the original construction edition into new remedial work, or automatically select the newest published edition.

### Comparison

Example question: "Compare the reasoning and repairs used in these reports and identify differences in class, edition and construction system."

The application presents findings side by side, preserving source-specific differences. Clause renumbering and clause equivalence are separate concepts.

## Main user journey

1. The user opens the local application and sees library, service/model and reference-coverage readiness.
2. The user imports company reports and supplies available original code/standard documents, tagged with source role and edition metadata for review.
3. Processing preserves images and source locations, organises defect items/occurrences and proposes relationships. The user can continue working with the published library while other files process.
4. The user opens the review queue for ambiguous identifiers, missing attachments or conflicting extracted facts. Broad historical research does not require every relationship to be reviewed first.
5. The user searches a defect description or exact source identifier, or starts a research question. A current project is optional for historical research.
6. For applicability, the user selects the affected building part and original/remedial work context. The application reuses existing sourced facts and asks only for required gaps.
7. The agent retrieves comparable findings, follows reasoning/source/repair graph links and fetches original passages and visuals.
8. The answer shows the requested findings, reasoning, repair alternatives, source extracts and applicability decision or unresolved conditions.
9. The user opens the source viewer or graph to inspect the evidence. A correction triggers dependent updates and marks earlier affected answers stale.
10. The question, answer and evidence snapshot are saved. Continuing later creates a new run using the current published knowledge and context.

### Worked product example

Question: "Find previous planter-box waterproofing failures. Show the reasoning, repair scope and AS details used, and tell me what needs checking for our current building."

The product searches equivalent terminology and retrieves relevant planter occurrences from previous reports. From the sample, it can show the Planter Box Membrane discussion, associated DS/location findings, original photographs and the embedded AS 4654.2-2012 Figure 2.17 on printed source page 30. Graph links bring together the report's discussion of membrane termination, porous concrete, drainage/overflow issues and remediation.

The historical answer attributes those statements to the report. The current-building section separately checks building part/class, jurisdiction, approval/work evidence, code volume/edition, standard reference chain and any recorded compliance solution. If approval evidence or original-source context is missing, it returns the useful historical material and names the unresolved applicability condition.

The user can open the figure, read the associated reasoning, inspect the chain to its identified source and compare repair options from other reports. The presence of the figure does not itself certify that AS edition for the current work.

### Key user stories

| Story | User intent | Acceptance |
|---|---|---|
| US01 | Find earlier cases of an issue described in my own words. | Comparable occurrences, match explanations and sources are returned even when terminology differs. |
| US02 | Understand why the expert considered an item defective. | Observations, attributed reasoning, requirements and supporting extracts can be followed together. |
| US03 | Reuse the actual AS/BCA image from an earlier report. | Exact and semantic searches return the preserved image and its report/source context. |
| US04 | Check requirements for this building part and work. | The product shows a sourced applicability decision or specific unresolved facts/rules/sources. |
| US05 | Compare remedies without losing their limitations. | Options, prerequisites and original/remedial contexts remain separate and attributed. |
| US06 | Correct an extraction error once and rely on the correction. | The correction is audited, affected projections update and stale research is identified. |
| US07 | Ask for all matching occurrences. | A complete paginated set or an explicit incomplete denominator is returned. |

## Required answer contents

An answer must include the requested portions of the following structure:

| Answer section | Required behaviour |
|---|---|
| Comparable findings | Identify the source report, finding number, relevant element/location and why it matches the question. |
| Observations | Describe what the report recorded, with linked photographs, tests or text where available. |
| Authored reasoning | Explain the report author's recorded reasoning and distinguish it from an inference made by the application. |
| Classification | Identify the relevant building part and source of its class assertion; show disputes or uncertainty. |
| Applicable requirements | Give edition, volume, amendment/variation and clause identity, original source and applicability rationale. |
| Referenced documents | Identify the relevant standard/document edition and the context in which it is referenced. |
| Remediation | Attribute each previous recommendation to its finding and retain prerequisites, limitations and alternatives. |
| Evidence gaps | Name the missing approval fact, source text, unresolved condition or conflicting evidence. |
| Sources | Provide clickable anchors and quotations sufficient to inspect the claim in context. |
| Visual evidence | Return relevant original screenshots, figures, tables, drawings or photographs with captions, report location, source-fragment identity where established and identification/verification gaps. |

Applicability statuses are **supported**, **excluded** and **unresolved**. "Supported" means the application's declared coverage and required checks support the decision; it is not a certification.

For historical research, the application may show a clause as **cited in the report**. That status is different from **original text verified** and **applicability supported**.

## Functional requirements

P0 means required for the first complete release. P1 means a later improvement.

| ID | Priority | Requirement |
|---|---|---|
| FR01 | P0 | Import DOCX, text PDFs and scanned PDFs. Legacy DOC must have an explicit conversion path or a visible unsupported-file result. |
| FR02 | P0 | Preserve immutable originals, document families and versions. Handle exact duplicates and linked Word/PDF renditions without double-counting a finding. |
| FR03 | P0 | Preserve immutable originals plus a versioned structured document tree, ordered blocks/tables/cells and all media occurrences/captions with exact locators. Keep logical assessment units and source-spanned chunks separately. OCR/layout includes image-only extracts and uncertainty. |
| FR04 | P0 | Extract defect items and individual occurrences, connecting each to its observations, extent/status assessments, authored reasoning, consequences, references, responsibility assessments and remediation options. Shared report sections require supported scope and cannot be assigned by proximity alone. |
| FR05 | P0 | Store source-backed project facts, their review status and conflicts. Keep original assessment and proposed remedial work contexts separate. |
| FR06 | P0 | Maintain one governed domain ontology; extract typed entity/assertion instances and link chunks through supported mentions/spans/scope. Keep building, concrete finish and membrane classes distinct. New terms need catalog review; class candidates require sourced facts and reviewed versioned definitions. |
| FR07 | P0 | Use a knowledge graph for finding-to-evidence and finding-to-requirement traversal. Every factual relationship must retain provenance and assertion status. |
| FR08 | P0 | Combine semantic and BM25 retrieval, support exact reference lookup, diversity and consistent versioned chunk metadata. Structure-aware child retrieval must fetch required full parent/dependency context. Historical and governing-source eligibility remain separate. |
| FR09 | P0 | Resolve BCA/NCC applicability from reviewed rules, jurisdiction and the relevant approval/work context. Support amendments, transition conditions and provision-specific exceptions. |
| FR10 | P0 | Retrieve original clause/table/figure context from the selected code edition, volume and amendments, and follow scoped reference chains to exact AS parts, years and amendments. Preserve exceptions and notes; year-ordering or newest-edition heuristics cannot select an adopted standard. |
| FR11 | P0 | Account for recorded Deemed-to-Satisfy, Performance Solution or combined pathways before making a non-compliance assertion. |
| FR12 | P0 | Retrieve and compare authored remediation options with prerequisites, limitations, alternatives and verification criteria where recorded. Keep proposed work separate from previous repair events and documented outcomes, and distinguish earlier recommendations from new application-generated proposals. |
| FR13 | P0 | Use LangGraph StateGraph workflows to plan, retrieve, inspect gaps, iterate and verify, with durable checkpoints, typed missing-fact interrupts and idempotent replay. Enforce permissions and cumulative budgets across retries/resumes. |
| FR14 | P0 | Ground factual claims in resolvable source anchors. Return supported sections with explicit partial/unresolved status when other sections cannot be supported. |
| FR15 | P0 | Let the user review and correct extracted assertions, with an audit trail. Corrections must invalidate affected indexes, applicability decisions and stale answers. |
| FR16 | P0 | Display source, fragment, reference-chain and rule coverage by jurisdiction, edition and relevant scope, with a demand list for missing originals. Support progressive library growth; unsupported coverage must not become an endorsed applicability decision. |
| FR17 | P0 | Record reproducible run evidence, rule/index versions, tool activity and model usage. Keep company document processing and external provider destinations explicit. |
| FR18 | P0 | Use structured enumeration for requests about all matching findings or reports. Report incomplete processing or pagination instead of claiming complete coverage from top-k search. |
| FR19 | P0 | Assess original work and proposed remedial work separately and show when applicability differs or remains unresolved. |
| FR20 | P1 | Offer user-initiated exports of selected findings and evidence into editable research notes. |
| FR21 | P1 | Add advanced interpretation/diagnosis from site photographs, corpus-wide synthesis and further jurisdictions after separate evaluation and reviewed coverage. P0 includes stored visual retrieval, OCR/layout and source-linked diagram descriptions under FR22. |
| FR22 | P0 | Search embedded BCA/AS extracts, tables, figures and drawings through exact identifiers, OCR/keyword/semantic retrieval and graph links. Return stored original visuals with each report occurrence, related reasoning, source identity, identification/verification state and cropped-context warnings. Generated diagrams cannot substitute for evidence. |

## Applicability requirements

The ontology defines the concepts and relationships; explicit checks enforce the decision conditions. Required facts can include jurisdiction, intended use, building-part classification, approval/application pathway and dates, work scope, relevant construction attributes and recorded compliance solutions. A rule can require additional facts for a particular provision.

Building classification must account for individual building parts and relevant exceptions. The NCC classification provisions address use and mixed classifications. [NCC building classification](https://ncc.abcb.gov.au/editions/ncc-2022/adopted/volume-one/a-governing-requirements/part-a6-building-classification)

The agent must first look for recorded classification evidence. Where a class is not stated, it must evaluate the relevant definition conditions against sourced building-use and configuration facts. It must explain any derived classification through those facts and rules, and identify missing conditions. Users are not required to classify every report manually before searching.

Edition selection must use the relevant jurisdiction rules, rather than the report date, inspection date or current clock alone. NSW guidance illustrates different certificate pathways and special staged-building arrangements; it is an example rule source, not the default jurisdiction for every project. [NSW edition guidance](https://www.nsw.gov.au/housing-and-construction/compliance-and-regulation/how-to-comply-national-construction-code)

Original referenced-document text must be checked against the particular reference and edition. The NCC referenced-document provisions address both edition identity and reference context. [NCC referenced documents](https://ncc.abcb.gov.au/editions/ncc-2022/adopted/volume-one/a-governing-requirements/part-a4-referenced-documents)

The required AS edition is established by the relevant code's scoped reference and adopted edition/amendments, not by selecting a year earlier than the BCA year. Secondary references and Performance Solution document bases also require the applicable edition/pathway rules. A screenshot's visible year establishes source identification, not project applicability or complete original-source verification.

The compliance pathway must be preserved because NCC compliance may use a Performance Solution, a Deemed-to-Satisfy Solution or a combination. [NCC compliance pathways](https://ncc.abcb.gov.au/editions/ncc-2022/adopted/volume-one/a-governing-requirements/part-a2-compliance-ncc)

These sources establish domain requirements. Implementation requires reviewed historical rules and reference coverage for the actual pilot projects.

## User interface

| Screen | Main actions |
|---|---|
| Home and workspace health | Show ready/partial reports, finding/media counts, review items, coverage gaps and service/model readiness with links to resolve them. |
| Report library | Import files/folders, inspect versions, view stage-specific indexing status, archive a report from active research and open originals. |
| Findings explorer | Search and filter findings by defect, element, location, report, class and source context. |
| Project context | Inspect extracted facts, review conflicts and provide missing information with recorded provenance. |
| Research workspace | Choose a research mode, ask questions, inspect evidence and follow targeted clarification requests. |
| Source viewer | Open PDF pages or Word paragraph/table locations; zoom original image extracts and show captions, reasoning, source year/volume/part/fragment and distinct report/source locators. |
| Finding graph | Follow sourced relationships and inspect the passage behind each assertion. |
| Reference and rules library | Inspect code volumes and AS editions/amendments, adopted/reference relationships, source demands, coverage and reviewed rule versions. |
| Settings and run history | Configure model destinations and budgets; inspect previous runs and stale status. |
| Review queue | Resolve uncertain associations, identifiers, OCR and context conflicts with the original evidence visible alongside the proposed correction. |

The research workspace has a question/mode/project control, answer area and evidence panel. The finding detail groups observations, result/status, reasoning, requirements, responsibility and remediation; it links individual occurrences and shared sections explicitly. The source viewer can remain open alongside an answer so the user can inspect evidence without losing the question.

Import screens distinguish queued, parsing/OCR, extraction, awaiting model configuration, review, indexing, ready, partial and failed states. Partial files are usable within their published coverage. Errors identify the file/stage and offer retry or a targeted correction rather than silently disappearing.

Search distinguishes an empty result from an unprocessed library or unavailable service. The applicability panel separates a report-cited year, identified original source and supported governing decision. Source badges use plain labels such as Report opinion, Embedded extract, Original source matched and Applicability unresolved.

Production users must not be able to disable ontology, provenance or applicability enforcement for an answer that claims governing requirements. Retrieval ablations belong in the evaluation tools.

## Release targets

These are acceptance targets for the pilot, not measured results or guarantees about an untested corpus.

| Measure | Target and denominator |
|---|---|
| Source resolution | 100% of citations in accepted answers resolve to the correct immutable source and location. |
| Critical applicability cases | All reviewed release fixtures pass; zero accepted wrong-edition or wrong-class governing claims in that suite. |
| Handling unknowns | All missing-context, unavailable-source and rule-conflict fixtures return the expected unresolved/partial status. |
| Retrieval | Mean recall@10 of at least 90% for held-out historical-search questions with at most ten reviewer-designated key findings. Complete-set questions use the separate enumeration gate. |
| Claim support | At least 95% of factual claims in accepted pilot answers are supported under human review; critical clause/applicability failures still block release. |
| Completeness | All enumeration fixtures return the full expected set or an explicit incomplete status and reason. |
| Direct finding search | p95 within 5 seconds on the declared pilot machine and corpus. |
| Agent run | Target p95 within 120 seconds for standard pilot queries; bounded execution must return a useful status when the limit is reached. |

The initial capacity profile is up to 100 reports, approximately 5,000 pages and 50 MB per input file. This is a planning assumption to validate with the user's actual library. Ingestion is asynchronous and exposes progress; no OCR throughput is promised before measurement.

The sample's numerous embedded images must be represented in the capacity benchmark, not just its text. Benchmark a concurrent import and research query, source-image zoom, large occurrence lists and graph expansion. Hardware and exact component versions are recorded with each result.

The pilot must include at least 50 held-out questions across representative reports and reviewed applicability fixtures. The author's prior opinions are ground truth for faithful extraction of those opinions; a competent reviewer establishes the applicability ground truth.

## Operational requirements

- Store original files, extracted records and indexes locally by default.
- Bind the initial server to the local machine and protect file access and state-changing operations.
- Configure external model/embedding endpoints explicitly before transmitting company content. Image pixels and page crops require explicit processing destinations independently from text configuration. Support a local-compatible provider.
- Parse document content as data. Embedded instructions, macros and document links cannot change agent permissions.
- Preserve the last published usable index if a new import or index update fails.
- Back up the original library and canonical records; treat vector and graph indexes as rebuildable projections.
- Display degraded services and reference gaps without silently substituting model memory for missing evidence.

## Scope boundaries

The first release does not generate signed expert reports, certify compliance, diagnose a new physical defect solely from a photograph, automatically select repairs for site execution, scrape every standard, train a model on company reports, or provide an unrestricted agent that modifies company systems.

Previous recommendations and inferred suggestions remain distinguishable. Actual repair success is recorded only where a source documents the outcome.

## Delivery stages

| Stage | Deliverable | Exit condition |
|---|---|---|
| M0 | Product corpus and executable stack baseline | Pilot fixtures, source/edition scope, provider policy and pinned stack pass the compatibility checks in TASKS.md. |
| M1 | Source library and visual ingestion | The user imports the sample and representative reports, inspects originals/images and sees source-preserving processing/review outcomes. |
| M2 | Connected domain knowledge and search | Item/occurrence extraction, operational ontology, Neo4j relationships and hybrid/image retrieval work with inspectable provenance. |
| M3 | Versioned requirements and applicability | Original reference chains, building-part definitions and reviewed original/remedial applicability fixtures pass. |
| M4 | Complete research workflow | Agent, verification, context/review UI, source/graph viewers, saved runs and all P0 features work together. |
| M5 | Accepted local release | Held-out evaluation, backup/recovery, capacity and all P0/operational checks pass on the recorded pilot machine. |

M1–M3 are development milestones. The complete product requires M4 and the M5 release checks. The [implementation backlog](TASKS.md) defines ordered tasks, dependencies, outputs and completion criteria for these milestones.

## Decisions to resolve from the pilot

| Decision | Current specification |
|---|---|
| First jurisdictions and historical editions | Select from the actual project reports; declare supported coverage explicitly. No jurisdiction is inferred from the computer's timezone. |
| Standards and specification access | Use original documents the company can supply or otherwise access appropriately. Record missing editions. |
| Initial corpus and report templates | Select representative DOCX, text PDF and scanned PDF examples with known findings and expected links. |
| Model deployment | Selected baseline: local BGE embeddings/OCR and the role-specific OpenAI profile in SPEC.md. Enable the actual account/destinations explicitly; validate any alternative provider and freeze its profile before release. |
| Source-code reuse | Licensed adaptation where rights exist, otherwise separately written modules implementing the required capabilities. |

## Related documents

The [technical specification](SPEC.md) defines LangGraph, the selected stack and service/API/UI contracts. [DATA_PIPELINE.md](DATA_PIPELINE.md) defines structured storage, exact chunking, metadata, ontology mappings and graph construction. The [domain ontology](ONTOLOGY.md) explains meaning and relationships. The [implementation backlog](TASKS.md) turns these contracts into ordered work. [Acceptance tests](ACCEPTANCE_TESTS.md) map requirements to observable behaviour; their execution is a release activity.
