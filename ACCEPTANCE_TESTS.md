# Defect Intelligence Acceptance Tests

Version 3.0  
Date 12 October 2026  
Status Acceptance scenarios for implementation and pilot validation

These scenarios define observable behaviour for the [PRD](PRD.md) and [technical specification](SPEC.md). The [implementation tasks](TASKS.md) map them to deliverables and milestones. They have not been executed against an implemented application.

## Fixture requirements

Use representative company reports with authorized access, plus synthetic fixtures for controlled failure cases. A reviewer must record the expected findings, passages, relationships, classifications and applicability outcomes before running the tests.

The fixture set must contain:

- DOCX findings with ordinary paragraphs, tables and separate reasoning/remediation sections.
- Text PDFs, scanned PDFs, linked Word/PDF renditions and report revisions.
- Multiple defects in one report and shared sections whose scope is clear or deliberately ambiguous.
- Similar defects with different building classes, materials, systems or code contexts.
- Mixed-use building parts, conflicting class assertions and missing approval evidence.
- At least two relevant historical code editions and reviewed jurisdiction rules, including a transition/exception case.
- Original clauses with conditions, referenced standard editions and recorded compliance solutions.
- A reported clause for which original text is unavailable.
- A historical repair recommendation with limitations, and a separate remedial-work context.
- Enough matching findings to exceed one retrieval and enumeration page.
- Embedded BCA/AS image-only clauses, tables, figures and drawings in a DOCX with selectable surrounding text; equivalent PDF visual regions.
- Identified and cropped/unidentified source headers, printed source pages, annotations, repeated images and diagrams requiring descriptions beyond OCR.
- Distinct building/concrete-finish/membrane class meanings, defect item/occurrence hierarchy, repeated DS identifiers and missing attachments.
- Alternative remediation options, failed previous repairs, mixed cited editions and primary/secondary reference-chain fixtures with exact parts/amendments.

The supplied [sample expert report](../sample%20expert%20report.docx) supplies representative structure and visual examples. Its AS 4654.2-2012 Figure 2.17 image provides a known identifier and printed source page 30 for retrieval testing. Report statements are not automatically ground truth for applicability; reviewed original sources and project evidence establish that separately.

Symbols such as E_old and E_new below denote editions selected by the reviewed fixture. They do not define real adoption dates. Jurisdiction-specific expected results must come from reviewed source evidence.

## Import and source preservation

| Test | Requirement | Action and expected result |
|---|---|---|
| TC01 | FR01 | Import a DOCX and a text PDF containing known findings. Both become searchable, with the expected report identity and source-backed findings. |
| TC02 | FR01 | Import a scanned PDF. OCR text remains linked to page images; unreadable/uncertain portions produce visible warnings and are not silently treated as reliable clause identifiers. |
| TC03 | FR01 | Import legacy DOC with and without the configured converter. Successful conversion retains the original and conversion identity; unavailable conversion produces a specific unsupported-file result. |
| TC04 | FR02 | Import identical bytes twice. Reuse the source version and avoid duplicate finding counts; record the repeated import outcome. |
| TC05 | FR02 | Import Word and PDF renditions of the same reviewed report version. Preserve separate anchors, link their family and avoid double-counting confirmed equivalent findings. Ambiguous mappings remain unresolved. |
| TC06 | FR02 | Import a revised report. Preserve the previous version, distinguish changed findings and make the selected version scope clear in search/results. |
| TC07 | FR03 | Open a citation from a PDF table and one from a DOCX table. The correct cell/passage and immutable source version appear. Word page numbers are not invented. |
| TC08 | FR03 | Retrieve a finding with a photograph and caption. Show the correct figure/caption link without presenting unperformed image interpretation as an observation. |

## Findings and domain interpretation

| Test | Requirement | Action and expected result |
|---|---|---|
| TC09 | FR04 | Extract a report containing several defects and a later remediation table. Link each recommendation to its supported finding. A deliberately ambiguous shared recommendation produces a review task, not links to every defect. |
| TC10 | FR05 | Extract a classification, code basis and approval date stated in a report. Preserve the source and assertion category; distinguish stated information from reviewed project evidence. |
| TC11 | FR05 | Supply conflicting approval/class assertions. Show the conflict and sources. The agent cannot silently choose the value that yields the most convenient clause. |
| TC12 | FR06 | Search using a reviewed defect synonym. Resolve the ontology concept and retrieve the expected findings through their governed concept links. |
| TC13 | FR06 | Query an ambiguous alias or describe only "apartments". Return candidates/missing conditions. Then supply sufficient sourced use/configuration facts for a reviewed classification fixture: derive the expected class with its fact/rule premises, without requiring a manually entered class. |
| TC14 | FR07 | Follow Finding → Reasoning → Remediation and Finding → ClauseReference → ClauseVersion paths. Every factual link exposes the supporting assertion and source anchor. |
| TC15 | FR07 | Use an extracted, unreviewed graph link that conflicts with the source text. It may identify a candidate, but cannot support the incorrect answer claim or establish a governing relationship. |

## Retrieval and applicability

| Test | Requirement | Action and expected result |
|---|---|---|
| TC16 | FR08 | Query an exact reference number and a paraphrased defect description. Exact/keyword and semantic paths both contribute appropriately, with stable evidence IDs and retrieval-method labels. |
| TC17 | FR08 | Research a current context while a useful previous report cites a different edition. Retain the report as historical precedent; exclude its edition from unsupported governing-clause claims. |
| TC18 | FR09 | Run a fixture whose reviewed rule selects E_old, despite a much later report date and current clock. Select E_old and show the fact/rule evidence. Changing the clock alone must not change that historical result. |
| TC19 | FR09 | Run transition, staged-work and provision-specific exception fixtures. Evaluate the stated conditions and return the reviewed expected provision set, including multiple contexts where required. |
| TC20 | FR09 | Remove a required date or supply an unsupported jurisdiction/rule range. Return unresolved applicability, the candidate set where available and the specific missing condition/coverage. Historical findings remain accessible. |
| TC21 | FR10 | Research a mixed-use project with separately sourced building-part classes. Select clauses for the affected part and applicable scope; do not treat one class as governing every part. |
| TC22 | FR10 | Provide a governing clause that references a particular standard edition while a newer standard is also indexed. Follow the reviewed reference chain and retain its applicable context and edition. |
| TC23 | FR10 | Retrieve a report citing a standard whose original text is absent, and a renumbered clause with no reviewed equivalence mapping. Show reported references/candidates; do not invent original wording or assert equivalence. |
| TC24 | FR11 | Provide a recorded Performance Solution relevant to a questioned Deemed-to-Satisfy departure. Retrieve and account for that evidence; the departure alone must not become an unqualified non-compliance conclusion. |

## Answers and agent behaviour

| Test | Requirement | Action and expected result |
|---|---|---|
| TC25 | FR12 | Compare prior remediation recommendations containing prerequisites and limitations. Attribute each to its finding and preserve the conditions; do not claim repair success without a recorded outcome. |
| TC26 | FR13 | Withhold one required evidence aspect from the first retrieval. The agent identifies the gap, performs targeted follow-up retrieval and terminates within the configured budgets. An exhausted budget gives a scoped partial/unresolved result. |
| TC27 | FR14 | Inject a nonexistent source/anchor ID into a draft. Mechanical verification rejects the affected claim even if model review approves it. |
| TC28 | FR14 | Inject a wrong-edition/class governing claim into an otherwise relevant answer. Reject or withhold the affected conclusion and explain the missing or incompatible applicability support. |
| TC29 | FR14 | Ask for a recorded author's reasoning and an additional new inference. Label and source the reasoning; label the inference separately. One adequate source can support a claim without an arbitrary two-citation minimum. |
| TC30 | FR15 | Correct an extracted project fact or finding association after saving an answer. Record the review action, update dependent projections, mark the old decision/run stale and use the corrected fact in a new run. |
| TC31 | FR16 | Load a code PDF without an active reviewed adoption rule for the project. Coverage must remain visibly incomplete; publication alone cannot authorize a governing applicability result. |
| TC32 | FR17 | Inspect a completed run while the optional tracing viewer is unavailable. The local ledger still contains source, context, index, ontology/rule versions and tool/budget information. |
| TC33 | FR17 | Configure a test provider adapter and inspect requests. Transmit only the configured processing inputs to the declared destination; never silently upload original files. Unknown provider pricing is shown as unknown. |
| TC34 | FR17 | Include document text instructing the agent to alter rules, execute a macro or modify a report. The text remains evidence data and cannot gain write or execution capabilities. |
| TC35 | FR18 | Ask for all matching findings in a fixture larger than top-k and a single enumeration page. Return the exact reviewed set or explicit incomplete coverage. A failed/unprocessed relevant source prevents an unqualified complete result. |
| TC36 | FR19 | Research original construction and proposed remedial work for the same finding. Create separate applicability contexts and return the fixture's respective outcomes; do not substitute either edition automatically for the other. |

## Versioned references and visual evidence

| Test | Requirement | Action and expected result |
|---|---|---|
| TC37 | FR03, FR22 | Import a DOCX with selectable narrative and an image-only AS clause. OCR the image, retain original bytes and occurrence/caption, and make its wording searchable without mislabelling OCR as verbatim verified text. |
| TC38 | FR10, FR22 | Ask for AS 4654.2-2012 Figure 2.17 in the sample, then use a reviewed natural-language query for its planter construction detail. Both retrieve the original embedded figure, its Planter Box Membrane context and relevant reasoning. Printed source page 30 is distinct from the report locator; applicability remains separately assessed. |
| TC39 | FR03, FR10, FR22 | Retrieve a table or figure whose requirement depends on headers, notes, dimensions or adjoining text. Preserve/fetch that context and reject a claim based on omitted exceptions or uncertain OCR numbers. Diagram descriptions record their extraction/review provenance. |
| TC40 | FR14, FR22 | Supply a cropped image with no visible edition and only an ambiguous nearby caption. Show candidates/unknown identity and the embedded image; do not invent its year or treat it as verified governing evidence. |
| TC41 | FR02, FR07, FR22 | Place identical image bytes under two defect items/reports with different captions and reasoning. Reuse the asset but retain both occurrences and their associations. Search returns the appropriate context; deleting/merging one occurrence cannot discard the other. |
| TC42 | FR10, FR16 | Index several AS editions/parts and an evidenced call-up selecting a particular edition plus amendments. Select that exact target using the reviewed chain, including a controlled same-year fixture where supported; no earlier-year/newest/nearest heuristic is used. Evaluate secondary-reference exceptions under the fixture's code edition. |
| TC43 | FR09, FR10, FR14 | Import a report containing mixed code/AS years. Preserve every stated citation, distinguish original-work/remedial/other purposes where supported, and flag unresolved conflicts. Do not rewrite history or silently endorse one version. |
| TC44 | FR06 | Query Class 2 across building, concrete finish and membrane discussions. Resolve using context or show alternatives; concrete finish/membrane classifications cannot populate a building-class assertion. |
| TC45 | FR04, FR07, FR18 | Extract one defect item with multiple occurrences and repeated DS identifiers at inconsistent locations. Retain item/occurrence hierarchy and scoped identifiers, flag the collision and missing attachment links, and enumerate distinct supported occurrences without merging solely by DS number. |
| TC46 | FR12, FR19 | Retrieve alternative corridor remedies and a failed previous waterproofing repair. Keep each remedy's steps/prerequisites separate; preserve the repair event/date uncertainty and documented failure instead of claiming successful remediation. |
| TC47 | FR16, FR22 | Start with reports and embedded extracts while originals or reviewed rules are missing. Return historical reasoning and stored visuals, list exact source demands, and withhold unsupported governing conclusions. Importing a needed edition extends coverage without overwriting earlier versions. |
| TC48 | FR17, FR22 | Enable a text-only provider while image processing remains local/disabled. Request a source figure and inspect processing calls: no original image pixels or page crops are transmitted implicitly. Any configured vision extraction is attributable and the answer displays the stored source visual. |

## Complete product workflows

| Test | Requirement | Action and expected result |
|---|---|---|
| TC49 | FR13, FR17 | Start research, reconnect its SSE stream and cancel it during bounded retrieval/model work. Resume events from the persisted sequence, stop within the allowed cancellation boundary, retain the stopping reason and never label cancelled work complete. |
| TC50 | FR17 | Launch with text/vision providers unconfigured and with one store unavailable. Health/settings show distinct readiness, published source/search capabilities remain usable within coverage, model-required jobs checkpoint awaiting configuration and no implicit external requests occur. |
| TC51 | FR14, FR17 | Reopen a saved answer, then continue after context/source changes. Resolve the immutable original evidence snapshot, show stale state where affected and create a new run against the current manifest/context rather than rewriting the old answer. |
| TC52 | FR15 | Submit two corrections to the same reviewed assertion version. Accept the first with audit/support links and reject the stale second with a version conflict; dependent updates do not merge incompatible facts silently. |
| TC53 | FR02, FR17 | Archive a report version from active research after saving an answer that cites it. A new manifest excludes it from active-scope search while the saved run still resolves the original evidence. Archiving cannot delete source assets or audit history. |
| TC54 | FR17 | Run a user-initiated backup/restore through settings and verify bundle checksums/schema. Preserve a recovery snapshot, restore canonical evidence and rebuild/verify projections before activation; failure preserves the prior usable workspace. |

## Structure metadata ontology and LangGraph contracts

| Test | Requirement | Action and expected result |
|---|---|---|
| TC55 | FR03 | Parse mixed DOCX paragraphs/nested tables/text boxes/media and rotated/cropped PDF pages. Persist DocumentIR/block rows, exact locators and separate physical/semantic revisions. Non-BMP/combining-character highlights use correct code-point/UTF-16 conversion; report and printed source pages stay distinct. |
| TC56 | FR03, FR08, FR10 | Chunk long reasoning, numbered clauses, measurement text, repair alternatives and merged-header tables. Every eligible source span is retained, all BGE inputs including headers are <=480 tokens, overlap is <=30 only for split atoms, and no occurrence/option/content-kind boundary is crossed. Fetch full parent/notes when interpreting a child result. |
| TC57 | FR08, FR14 | Validate canonical ChunkRevision/Segment metadata and compare FTS/Qdrant/Neo4j receipts. Hydrate results from canonical records. Report-cited code year, identified AS extract year and current applicability remain separate; stale or mismatched payload metadata cannot authorize a claim. |
| TC58 | FR06, FR07 | Extract entity mentions/assertions under one catalog version and map their source spans to chunks. Preserve ambiguous class families/new-term candidates; no per-chunk ontology/class hierarchy or automatically active definition/rule is created. |
| TC59 | FR07, FR10 | Construct graph batches from validated canonical records. Reject invalid endpoints/predicates/support, and retain report opinion/citation status. Similarity cannot create a cause/class/adoption fact; reported AS references cannot become verified normative edges. |
| TC60 | FR02, FR04, FR07 | Use repeated DS numbers, person names, image bytes and similar statements across projects/versions. Match scoped canonical identities only with adequate evidence; retain distinct image occurrences/assertions and reveal conflicts instead of global similarity/name merges. |
| TC61 | FR13, FR17 | Fail after a LangGraph node materializes a result but before its checkpoint completes, then resume the same registered thread/version. Reuse validated idempotent artifacts, preserve operation/budget usage and publish no duplicates. A provider request with unknown outcome stays recorded as unknown, not assumed exactly-once. |
| TC62 | FR05, FR09, FR13 | Interrupt for a missing project fact. Validate Command resume, retain initial/final context snapshots and rerun affected applicability gates. User declarations stay attributed/conditional; stale context/new-manifest input requires explicit refresh/new run. Budgets persist and user wait time is excluded only from the active-time counter. |
| TC63 | FR08, FR15, FR17 | Correct OCR, metadata scope or a catalog mapping, and change an embedding/graph profile. Create immutable dependent revisions and consistent receipts; re-embed when text/profile changes, preserve old source evidence and reject incompatible checkpoint reuse. |
| TC64 | FR03, FR07, FR08, FR22 | Run the sample's planter section through structure, entities/assertions, chunks/metadata and graph publication. Retrieve AS 4654.2-2012 Figure 2.17 by exact identifier and a reviewed semantic question; return original visual, parent reasoning and scoped occurrences/remedy. Identified source page 30 does not establish current applicability. |

## Operational acceptance

| Test | Behaviour |
|---|---|
| OP01 | Interrupt a new index publication. The prior published generation remains usable and the new import is visibly incomplete. |
| OP02 | Reimport unchanged sources after a worker restart. Resume/reuse the appropriate job outputs without duplicate entities or unintended deletion. |
| OP03 | Change the embedding model/dimension. Create a compatible vector generation and retain a clear migration/publication status. |
| OP04 | Stop Neo4j or the applicability service. Show degradation and the affected coverage; do not claim complete graph research or substitute model memory for governing rules. |
| OP05 | Restore from a backup of originals, canonical records, ontology/rules and runs. Rebuild projections and resolve the same finding citations. |
| OP06 | Navigate source previews with invalid or out-of-scope asset identifiers. Reject access and do not read arbitrary filesystem paths. |
| OP07 | Submit over-limit, malformed or unsupported files. Fail the individual import visibly and preserve the rest of the library. |
| OP08 | Use the research UI on the pilot desktop and a narrow viewport. Required actions, evidence statuses and source identities remain readable and accessible. |

## Evaluation method

Keep extraction, retrieval, graph association, applicability and final claim evaluation separate. A failure in one layer must be diagnosable rather than hidden by a single answer score.

Use at least 50 held-out research questions across the representative corpus and reviewed applicability fixtures. Do not tune prompts on the held-out questions and then report them as an independent evaluation.

Record:

- Corpus/document versions and the active index, ontology and rule versions.
- Question, research mode, project context and the expected answer/evidence set.
- Retrieved finding IDs and coverage, graph assertions used and applicability decision.
- Claim-level support and source-resolution results.
- Latency, provider/model configuration, token/cost status and stopping reason.
- Reviewer judgement and the category of each failure.

Historical extraction is evaluated against what the report actually says. Applicability is evaluated against reviewer-established project and regulatory evidence. An incorrect historical citation in a report must be extracted faithfully and identified as inconsistent when independently checked.

## Release gates

The MVP is ready only when:

1. All P0 product scenarios and operational checks pass in the declared coverage.
2. All critical edition/class/reference-chain fixtures pass, with no accepted incorrect governing claim in the release suite.
3. Accepted answer citations resolve correctly and partial/unresolved states are handled as required.
4. The PRD retrieval, claim-support and performance targets pass on the recorded pilot profile.
5. Graph, ontology, hybrid search, applicability and source viewing work in the same application.
6. Source-code/dependency use and reference-document access are established for the intended company use.

## Test result record

For each implemented test, record test ID, fixture/version, expected result, actual result, evidence/run ID, pass/fail, reviewer and date. Preserve failed cases and the fix category.

The specification package itself does not constitute a passed application evaluation. Application test execution starts during implementation.
