# Building Defect Knowledge Ontology

Version 1.0  
Date 12 October 2026  
Status Domain design for implementation  
Related documents [Technical specification](SPEC.md), [Data pipeline](DATA_PIPELINE.md), [Product requirements](PRD.md), [Implementation tasks](TASKS.md), [Acceptance scenarios](ACCEPTANCE_TESTS.md)

## Purpose and central concept

The ontology describes the knowledge needed to research building defects from the company's previous Word and PDF expert reports. It connects a defect at a particular location to the building element, observations, expert reasoning, requirements, evidence and proposed remediation. It also explains the building and work context needed to determine whether a requirement applies.

The central concept is a **defect assessment concerning a building element at a location**. A report can group many individual occurrences under one defect item. Those occurrences share some reasoning, but retain their own observations and sources.

For example, a report may contain a Rooftop Waterproofing item with several occurrences on different roofs. Membrane delamination on one roof and ponding on another are separate observations. The ontology connects each occurrence to the relevant photographs, locations and reasoning without treating every photograph as evidence of every listed defect.

This Markdown document defines the domain model for implementation. The operational ontology is planned as a governed JSON/canonical concept catalog with an in-memory RDF projection. TTL authoring requires a subsequent explicit user instruction.

## Relationship overview

~~~text
Project -> Building -> Building part -> Location -> Building element
                         |
                         +-> Building use and classification assessment
                         +-> Original construction and later work events

Report -> Defect item -> Individual occurrence -> Observations and tests
              |                   |
              +-> shared          +-> Expert assessment and reasoning
                  reasoning       +-> Causes and consequences
                                  +-> Requirements assessed against
                                  +-> Remediation options
                                  +-> Supporting evidence

Assessment context + project facts + reviewed rules
  -> Applicable code edition, volume and jurisdiction provisions
  -> Applicable clause and scoped reference relationship
  -> Exact Australian Standard edition and amendments
  -> Relevant AS clause, table, figure, appendix and notes

Evidence in report -> Text passage or image occurrence -> Original asset
Image extract -> Identified source edition and source fragment
~~~

These are domain relationships. Each factual link also needs its source and evidence status. A path through the graph makes evidence discoverable; it does not establish applicability or prove an expert's conclusion on its own.

## Buildings and their context

| Concept | Meaning and information to retain |
|---|---|
| Project | The job or development to which reports, approvals, drawings and work belong. Keep recorded identifiers and links to related documents. |
| Building | A physical building within the project. A project may contain several buildings. |
| Building part | An identifiable part with a particular use or assessment context, such as apartments, a shop tenancy or a basement carpark. |
| Location | The spatial description of a finding: building, level, unit, room, roof area, elevation or other identified place. Preserve the report's wording alongside resolved locations. |
| Building element | The physical element being assessed: membrane, slab, wall, door threshold, balustrade, drain or another component. |
| Construction system | How elements work together, such as an external waterproofing system or a single-skin concrete wall system. |
| Material and product | The material, proprietary product or assembly where known. An unknown membrane product remains unknown. |
| Building use | The documented purpose of a building or part, used as evidence when evaluating classification. |
| Environmental and construction conditions | Relevant facts such as UV exposure, habitable space below, height, construction type or an internal/external location. Required facts depend on the particular provision. |

Elements can connect across locations. A planter-box membrane can be associated with moisture damage in an apartment below or beside it. The ontology must retain the distinction between the suspected failure location and the location of consequential damage, with evidence for the proposed connection.

Interfaces are also meaningful: membrane-to-wall termination, slab-to-hob junction, door-to-waterstop junction and cladding-to-roof intersection. Defect search must support these interfaces rather than requiring the issue to belong to only one isolated element.

## Building classification

A building classification assessment associates a building or part with a class and subclass, the relevant use, the definition used, and the evidence supporting the assessment. It can be recorded in a certificate, stated in a report or derived through reviewed classification rules.

Keep the classification's source, relevant date/context, alternatives, review status and any unresolved condition. Definitions and exceptions must be linked to the code edition and jurisdiction provisions that supply them. A use description such as apartment is useful evidence but cannot alone confirm a classification.

Different parts can have different classes or multiple classifications. Classification for one part must not silently become the classification of every other part. Applicable classification relationships for associated outdoor areas or service rooms require the relevant definition/rule evidence. [NCC building classification](https://ncc.abcb.gov.au/editions/ncc-2022/adopted/volume-one/a-governing-requirements/part-a6-building-classification)

The sample report uses class terminology in several different senses:

| Classification concept | What it classifies |
|---|---|
| Building Class 2 | A building or building part under the relevant building classification provisions. |
| Concrete finish Class 2 | The specified quality of a concrete surface under the relevant specification/standard. |
| Membrane Class 1, 2 or 3 | A membrane classification in its particular standard/product context. |

These must be separate concepts, with separate aliases and definitions. The shared words Class 2 do not establish that they are equivalent.

## Work and approval context

Original construction, subsequent alterations, repairs already undertaken and proposed remedial work are separate work events or work packages. Keep what was done or proposed, the affected elements, relevant dates, source documents and recorded outcomes.

An assessment context identifies the building part, work package and purpose of the question. It links jurisdiction, classification, approval/application pathway and relevant dates to the particular requirement topic being assessed. Report publication, inspection, source publication and approval dates have distinct roles.

Approval and compliance evidence can include development consent, construction or occupation certificates, stamped drawings, declared designs, compliance certificates, inspections and recorded Performance Solutions. A certificate's statement is evidence of what was certified; it does not erase contrary site observations.

The original work and proposed remediation need separate applicability assessments. The app must neither automatically reuse the original code edition for later work nor select the newest published edition simply because it is available. Jurisdiction-specific rules and project facts establish the applicable context. [NSW edition guidance](https://www.nsw.gov.au/housing-and-construction/compliance-and-regulation/how-to-comply-national-construction-code)

## Code editions and volumes

A code edition is a particular published BCA/NCC edition and amendment/version. A volume is a component of that edition, with its own content and source identity. Jurisdiction provisions and effective/adoption information remain separately sourced and reviewed.

Record at least:

- The code family and edition year.
- Volume identity and title.
- Amendment or issue identity where applicable.
- Publisher, original source document and available coverage.
- Jurisdiction provisions or variations and their sources.
- Publication information, separately from adoption and project applicability.

For example, the sample's sewer and stormwater discussion contains NCC 2016 Volume Three extracts, while several building defect discussions use Volume One. The correct volume therefore depends on the requirement being researched; the building's class alone does not select every source volume.

Historical volume structure and terminology must come from the relevant edition. The [ABCB edition archive](https://ncc.abcb.gov.au/editions-national-construction-code) provides original historical editions; importing one is distinct from establishing its applicability to a project.

## Australian Standard editions and reference relationships

An Australian Standard family, such as AS 4654, can contain separate parts and editions. AS 4654.1 and AS 4654.2 are separate documents. Each edition needs its full identifier, part, year, amendments and source identity.

The ontology must distinguish the standard mentioned by an expert from the exact standard edition adopted or otherwise used in an assessment. It must not select a standard by the rule AS year is less than BCA year, by the nearest year, or by the newest available document.

A reference relationship records:

| Information | Purpose |
|---|---|
| Referencing provision and edition | Identify exactly where the document is called up. |
| Referenced document and edition | Identify the exact target, including part and amendments. |
| Reference basis | Distinguish an adopted normative reference, a secondary reference, a project specification, guidance or a reference reported by an expert. |
| Scope | Preserve the particular provisions, purpose, conditions and exceptions of the reference. |
| Evidence and resolution status | Distinguish a reported chain from an independently verified relationship. |

Primary, secondary and further references need their own chain evaluation under the applicable edition's rules. The sample's concrete-finish discussion connects BCA, AS 3600 and AS 3610. Preserve that reported chain, including the editions it cites, then check each link against original sources. [NCC referenced documents](https://ncc.abcb.gov.au/editions/ncc-2022/adopted/volume-one/a-governing-requirements/part-a4-referenced-documents)

Different bases can coexist. A standard might be relevant because the project specification requires it even where a particular NCC adoption relationship has not been established. Those bases must remain visible rather than being collapsed into a generic applies-to edge.

## Requirements and source fragments

A requirement is what must be achieved or complied with under its established basis and context. Its source can be a code provision, standard, project drawing/specification, manufacturer instruction or other document. The kind of source and its role matter to how the requirement is used.

Source fragments include clauses, subclauses, tables, figures, appendices, specifications, definitions, notes and guidance. Each fragment belongs to an identified document edition and has its own source location. A bare number such as 2.8 or Figure 2.17 is not a complete identity.

Retain parent provisions, referenced definitions, conditions, exceptions, table headers and accompanying notes. Diagrams can express relationships and dimensions that are absent from nearby prose. Commentary, examples and informative material need a recorded role; they must not be automatically promoted to mandatory requirements.

A compliance assessment connects a finding and its evidence to the requirements considered, the recorded compliance pathway and the expert's reasoning. It distinguishes a Performance Requirement, a DTS provision and a documented Performance Solution. A DTS departure alone cannot settle whether the relevant Performance Requirements are satisfied. [NCC compliance pathways](https://ncc.abcb.gov.au/editions/ncc-2022/adopted/volume-one/a-governing-requirements/part-a2-compliance-ncc)

Legal provisions cited in a report are also source fragments with jurisdiction, version/date and source identity. Keep them separate from BCA/AS technical requirements. The sample cites statutory warranty, major-defect and duty-of-care provisions; those citations and the expert's conclusions must be attributable to their sources rather than treated as automatic legal determinations.

## Defect items and individual occurrences

The sample groups discussion under topics such as Rooftop Waterproofing, Planter Box Membrane and Concrete Finish Quality. These are defect items, which can contain several different failure types and individual occurrences.

An individual occurrence identifies the affected element and location and retains the report's DS/finding references, photographs, observations and links to shared reasoning. Preserve the report's hierarchy and the evidence establishing each association. A paragraph's proximity alone is insufficient to assign it to a finding.

| Report concept | Meaning |
|---|---|
| Observation | What was recorded at the location, including its source and method. |
| Test or measurement | Reading, dimension, test method, instrument, units, date and conditions where recorded. |
| Expert assessment | The author's conclusion about the condition or departure, with its supporting reasoning. |
| Occurrence extent | The author's specific, recurring, systemic or other description of distribution. |
| Status assessment | Major/non-major or another authored status, with its cited basis and reasoning. |
| Cause assessment | A confirmed, suspected, alternative or unresolved explanation of the failure. |
| Consequence | Existing damage or a predicted consequence, kept distinguishable. |

Occurrence extent, physical severity and statutory major-defect status are separate assessments. One does not imply another. The classification of a building element as major must not alone create a major-defect finding.

An identifier is scoped to its report/version and authored schedule context. Repeated DS numbers, inconsistent locations or changing identifiers between revisions need review; they must not trigger automatic entity merging. References to missing schedules or attachments remain unresolved links.

## Reasoning and causation

Reasoning links the observations, reported history, construction details and requirements used to reach an assessment. It is attributable to an author and source passage. The application's later inference is a separate assessment with its own premises.

For a rooftop membrane, the report may record delamination and discuss substrate preparation, contamination or curing as possible causes. Preserve whether the author presents these as alternatives, a combination or a firm conclusion. Do not turn a list of possible causes into several independently confirmed diagnoses.

Connections between failure and damage need the same care. A report may attribute ceiling deterioration to a planter above. The graph can retrieve this chain, while retaining the evidence and certainty of the attribution.

Measurements retain their original values and units. OCR uncertainty in a decimal, slope ratio, membrane thickness or table value must remain visible. A moisture-meter display without an established measurement scale must not silently become a percentage.

## Remediation and repair history

A remediation option addresses an identified failure or consequence. It retains the recommending author, source, affected locations, scope, sequence, prerequisites, limitations and alternatives.

Prerequisites can include a regulated design, consent modification, access arrangements, manufacturer confirmation or temporary accommodation. Verification and acceptance criteria are recorded where supplied by a source or established in a separately reviewed proposal.

The sample's corridor discussion provides two options: enclosing corridor ends or undertaking corridor waterproofing works. Model them as alternatives with their own conditions and steps. The bathroom discussion also qualifies a local repair scope against a potentially wider reinstatement scope; preserve that qualification.

Previously undertaken repairs are work events, not recommendations. Their observed success or failure needs source evidence. A recommendation's presence in a report does not prove that it was implemented or effective.

## Parties and responsibility assessments

Parties have recorded roles, scopes, appointments and relevant source documents. The report may attribute responsibility to the builder, architect, certifier or waterproofer for a particular defect or omission.

Keep each attribution as an authored responsibility assessment, linked to its reasoning, work scope, schedule references and evidence. It is separate from physical causation and from a binding legal determination. A party's role alone cannot establish responsibility for every finding.

Certificates, drawings, specifications and inspection records can support or conflict with a responsibility assessment. Their authorship, dates and statements must remain inspectable.

## Evidence and embedded images

Evidence sources include company reports, original code/standard documents, drawings, specifications, manufacturer documents, certificates, inspections, photographs, tests and attributable reported history.

For an embedded image, distinguish three things:

1. **Original image asset:** the preserved image bytes and file identity.
2. **Occurrence in a report:** where this image appears, its caption, surrounding discussion and associated findings.
3. **Source fragment depicted:** the BCA/AS clause, table or figure, drawing detail or other source represented by the image, where identifiable.

Identical image bytes can be reused, while each occurrence retains a separate context. Different crops or annotations can depict the same source fragment without being the same image asset. Preserve all meaningful occurrences.

| Image information | What to retain |
|---|---|
| Image role | Site photograph, code extract, standard extract, table, figure, drawing, certificate or uncertain. |
| Report location | Document version, section, paragraph/table or PDF page and image bounds. |
| Source identity | Publisher/document, edition, volume or standard part, amendment, and how each was identified. |
| Source fragment | Clause, table, figure, appendix and printed source page where established. |
| Caption and relationships | Caption, surrounding reasoning, associated findings and requirements. |
| OCR and layout | Recognised text with regions, reading order, table structure and uncertainty. |
| Diagram information | Labels, relevant interfaces, dimensions and relationships, attributed to the extraction/review method. |
| Annotations | Highlights, arrows and comments, distinguished from the original source content where possible. |
| Verification | Whether the extract was matched against an original document, or remains an embedded extract only. |

For example, the Planter Box Membrane section includes an embedded image labelled **AS 4654.2—2012, Figure 2.17, Typical Planter Box Construction**, with printed source page **30** visible. The image connects to the report's planter-box assessment and reasoning, and separately to the identified standard fragment. This is identification from the supplied image; it does not independently verify the complete standard or its applicability.

A query for planter-box waterproofing details should retrieve that original image and the relevant report reasoning. A query for AS 4654.2-2012 Figure 2.17 should support exact lookup. A query for membrane termination below soil level should support text/semantic retrieval and graph expansion to associated extracts and drawings.

The returned visual must be the stored original or a clearly identified crop/preview of it. Generated diagrams must not replace source evidence. Cropped extracts may omit exceptions or notes; the answer must disclose the gap and retrieve complete source context where available.

## Evidence status and uncertainty

Keep these statuses separate:

| Dimension | Examples |
|---|---|
| Statement kind | Direct observation, reported history, expert opinion, user declaration, original-source text, application inference. |
| Extraction/review | Extracted, uncertain, reviewed, superseded. |
| Source identification | Identifier visible in image, inferred from caption, ambiguous, unknown. |
| Reference verification | Reported only, embedded extract identified, original source matched, conflicting. |
| Applicability | Supported, excluded, unresolved for a specific assessment context. |
| Repair outcome | Recommended, recorded as undertaken, outcome documented, outcome unknown. |

A reviewed report opinion remains an opinion. A readable screenshot remains an extract. Identifying its year does not establish that year as applicable to the project.

The sample mentions NCC 2016 as applicable in one discussion, NCC 2022 elsewhere, and different AS 3600 editions in different sections. Preserve those citations as stated, determine their respective assessment purposes, and flag unresolved inconsistencies. Do not silently replace them with a single assumed version.

Similarly, documentation not provided is different from documentation proven not to exist. Unresolved approval evidence, unavailable standards and ambiguous attachment links are explicit knowledge gaps.

## Building the source library and graph

### How chunks relate to the ontology

The ontology is one shared governed schema/catalog. Documents provide instances, such as a particular planter, observation, expert assessment, repair option or identified source figure. Chunks provide searchable evidence for those instances and their qualified relationships; they do not each receive a new ontology.

Extraction maps source-supported mentions to catalog concepts and canonical entities, then links chunk source spans or explicitly scoped shared context to those records/assertions. Building Class 2 and concrete finish Class 2 resolve to different concept families. Unknown terminology produces a review candidate rather than a new automatically published class or predicate.

Neo4j projects the validated entity/assertion/source records plus lightweight chunk/concept/evidence links. A similarity match does not create a factual cause, classification or adoption edge. [DATA_PIPELINE.md](DATA_PIPELINE.md) specifies the entity resolution, span mapping, metadata schema and construction stages.

### Progressive source coverage

Start with editions represented in the company's reports and pilot projects. Expand coverage as other years, volumes, standards or jurisdictions become necessary. The application does not require every historical BCA edition before report research can begin.

1. Import the Word/PDF reports and retain their structure, images and source locations.
2. Identify cited BCA/NCC and AS editions from text, captions and image contents.
3. Register a demand list of required original editions, parts, amendments and missing source fragments.
4. Import the relevant original code volumes, standards and project documents.
5. Identify their hierarchy and propose source-backed reference relationships for review.
6. Activate reviewed definition/applicability rules for the declared project coverage.
7. Publish searchable passages and image descriptions alongside the source-backed graph.

Search indexing makes passages and images discoverable. Graph construction identifies entities and establishes sourced relationships. Applicability evaluation uses project facts and reviewed rules. These are distinct operations.

Report research can return embedded extracts and useful historical reasoning while original-source coverage is incomplete. A governing conclusion requiring unavailable original context remains unresolved. Coverage must show source availability, extraction completeness, reference verification and rule readiness separately.

## Sample basis and implementation boundaries

The domain examples are based on the supplied [sample expert report](../sample%20expert%20report.docx), particularly Rooftop Waterproofing, Planter Box Membrane, Corridors & Foyer, Concrete Finish Quality, Builders Repairs - Waterproofing, Bathroom & Ensuite - Waterproofing & Ponding, and Duty of Care. They illustrate the report's structure and statements rather than determining the project's legal or technical compliance.

The technical specification maps these domain concepts into storage, ingestion, graph, retrieval and verification contracts. This document does not claim that a complete regulatory source library, revised executable ontology, applicability engine or application has been implemented.

The selected initial operational format is a governed JSON/canonical concept catalog with an in-memory rdflib projection for curated ontology lookup, as defined in SPEC.md. This supports implementation of the domain model without writing TTL files.
