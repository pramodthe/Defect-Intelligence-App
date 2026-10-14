"""Compile the reviewed domain design into a versioned JSON schema (no TTL authoring)."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'Context': 'Buildings and their context',
    'Classification': 'Building classification',
    'Work and approvals': 'Work and approval context',
    'Editions and references': 'Australian Standard editions and reference relationships',
    'Requirements': 'Requirements and source fragments',
    'Defects and assessments': 'Defect items and individual occurrences',
    'Reasoning': 'Reasoning and causation',
    'Remediation': 'Remediation and repair history',
    'Parties': 'Parties and responsibility assessments',
    'Evidence': 'Evidence and embedded images',
    'Governance': 'Evidence status and uncertainty',
}
# ID | parent | group | definition | properties. Source section is explicitly attributed below.
CLASSES = '''
DomainRecord||Governance|A versioned domain record with source identity, scope and independent evidence-status dimensions.|source_id,recorded_text,source_locator
Project|DomainRecord|Context|The job or development to which buildings, reports, approvals and work belong.|recorded_identifier,recorded_name
Building|DomainRecord|Context|A physical building within a project; a project may contain several buildings.|recorded_identifier,recorded_name
BuildingPart|DomainRecord|Context|An identifiable building part with its own use and assessment context.|recorded_name,recorded_use
Location|DomainRecord|Context|The report's spatial description, preserving wording and keeping failure and damage locations distinct.|recorded_location,location_role
BuildingElement|DomainRecord|Context|A physical component discussed by the report, with recorded or candidate identity and location.|element_category,recorded_name,resolution
ConstructionSystem|DomainRecord|Context|How recorded elements work together in a system; not inferred from similarity alone.|recorded_name,resolution
Material|DomainRecord|Context|A material explicitly mentioned or identified by the source.|recorded_name,resolution
Product|DomainRecord|Context|A proprietary product or assembly where recorded; unknown products remain unknown.|recorded_name,manufacturer,resolution
Interface|DomainRecord|Context|A sourced junction or interface between elements, such as a membrane-to-wall termination.|recorded_name,resolution
BuildingUse|DomainRecord|Context|Documented use of a building or part, retained as evidence rather than automatic classification.|recorded_use
EnvironmentalCondition|DomainRecord|Context|A recorded environmental condition, including exposure or habitable space below.|recorded_text
ConstructionCondition|DomainRecord|Context|A recorded construction condition, such as height, construction type or internal/external context.|recorded_text
Assessment|DomainRecord|Defects and assessments|An attributable assessment with premises, source, purpose and qualifications.|recorded_text,assessment_purpose
ClassificationAssessment|Assessment|Classification|An assessment of a particular subject using a stated classification definition and context.|class_identifier,definition_reference,assessment_date
BuildingClassificationAssessment|ClassificationAssessment|Classification|A building/part classification assessment; never propagated to other parts without support.|class_identifier,subclass_identifier,recorded_use
ClassificationDefinition|DomainRecord|Classification|An editioned original definition and exceptions used by a reviewed classification assessment.|class_identifier,definition_reference
BuildingClass|DomainRecord|Classification|A building or building-part class in its code/jurisdiction definition; distinct from finish and membrane classes.|class_identifier
ConcreteFinishClass|DomainRecord|Classification|A concrete surface finish classification in its specification or standard context.|class_identifier
MembraneClass|DomainRecord|Classification|A membrane classification in its product or standard context.|class_identifier
WorkEvent|DomainRecord|Work and approvals|Original construction, alteration or recorded repair with affected scope, dates and outcome evidence.|work_kind,work_date,recorded_outcome
OriginalConstruction|WorkEvent|Work and approvals|The original construction event, separate from subsequent or proposed work.|work_date,work_scope
Alteration|WorkEvent|Work and approvals|A later alteration with its own scope, approval and applicability context.|work_date,work_scope
RepairEvent|WorkEvent|Work and approvals|A repair reported or recorded as undertaken; a recommendation alone cannot create this event.|work_date,work_scope,recorded_outcome
ProposedRemedialWork|DomainRecord|Work and approvals|Proposed remedial work, kept separate from undertaken repairs and original construction.|work_scope
WorkPackage|DomainRecord|Work and approvals|A particular construction or remedial work scope used by an assessment context.|work_scope,work_kind
AssessmentContext|DomainRecord|Work and approvals|The building part, work purpose, jurisdiction, dates and approval pathway for a question.|assessment_purpose,jurisdiction,approval_pathway,relevant_dates
ProjectFact|DomainRecord|Work and approvals|A sourced project fact or attributed user declaration, retaining conflicts and unknown values.|fact_name,fact_value,fact_provenance
ApprovalRecord|DomainRecord|Work and approvals|A consent, certificate, stamped drawing or declared design; source statements do not erase contrary observations.|approval_kind,recorded_identifier,approval_date,recorded_text
ComplianceCertificate|ApprovalRecord|Work and approvals|An attributable statement of certification with recorded scope and source.|recorded_identifier,recorded_text
InspectionRecord|DomainRecord|Work and approvals|An inspection's recorded observations, author, dates and scope.|inspection_date,recorded_text
PerformanceSolutionRecord|ApprovalRecord|Work and approvals|A documented Performance Solution with stated scope and evidence; existence cannot be inferred from a DTS departure.|recorded_identifier,work_scope
SourceDocument|DomainRecord|Evidence|A report, original authority, drawing, specification, manufacturer instruction, certificate or inspection document.|document_role,source_availability
DocumentVersion|SourceDocument|Evidence|An immutable document version, distinct from editions it mentions.|filename,asset_hash,publication_date,inspection_date
ReportVersion|DocumentVersion|Evidence|A particular expert report version whose authored opinions and observations remain attributable.|filename,author_name,publication_date,inspection_date
Drawing|DocumentVersion|Requirements|A project drawing with identifier, revision and source scope.|recorded_identifier,revision_identifier
Specification|DocumentVersion|Requirements|A project specification, distinguished from code adoption and manufacturer guidance.|recorded_identifier,revision_identifier
ManufacturerInstruction|DocumentVersion|Requirements|An identified manufacturer's instruction and its product/edition context.|manufacturer,recorded_identifier,revision_identifier
CodeFamily|DomainRecord|Editions and references|A BCA/NCC document family, separate from its editions and volumes.|reference_family
CodeEdition|DomainRecord|Editions and references|A specific BCA/NCC published edition and amendment; publication alone does not establish adoption or applicability.|reference_family,edition_year,amendments,publisher,publication_date
CodeVolume|DomainRecord|Editions and references|An edition-specific volume with its own identity and source coverage; building class alone does not select it.|volume_identifier,recorded_name
JurisdictionProvision|DomainRecord|Editions and references|A separately sourced jurisdiction variation or effective/adoption provision.|jurisdiction,effective_date,recorded_text
StandardFamily|DomainRecord|Editions and references|An Australian Standard family, such as AS 4654, separate from parts and editions.|reference_family
StandardPart|DomainRecord|Editions and references|A particular standard part; AS 4654.1 and AS 4654.2 are not interchangeable.|reference_family,part_identifier
StandardEdition|DomainRecord|Editions and references|A specific part/year/amendment identity; reported citations remain unverified until original source review.|reference_family,part_identifier,edition_year,amendments,publisher
ReferenceRelationship|DomainRecord|Editions and references|An editioned, scoped reference link with explicit basis, conditions, exceptions and verification state.|reference_basis,conditions,exceptions,recorded_text
ReferenceChain|DomainRecord|Editions and references|A sequence of independently assessed primary, secondary or further reference links.|reference_basis,recorded_text
SourceFragment|DomainRecord|Requirements|An identified clause, table, figure, appendix, definition, note or detail in a specific source edition.|fragment_kind,fragment_identifier,printed_source_page,fragment_role
Clause|SourceFragment|Requirements|A clause or subclause with parent, definitions, conditions, exceptions and original context.|fragment_identifier,conditions,exceptions
Table|SourceFragment|Requirements|A table with its headers, notes, units and original reading structure.|fragment_identifier,units_as_written
Figure|SourceFragment|Requirements|A source figure with labels, dimensions, interfaces and original context.|fragment_identifier,printed_source_page
Appendix|SourceFragment|Requirements|An appendix with its recorded normative/informative role.|fragment_identifier,fragment_role
Definition|SourceFragment|Requirements|An editioned definition used by a requirement or classification assessment.|fragment_identifier
Note|SourceFragment|Requirements|A source note retained with its provision; its role is not automatically mandatory.|fragment_identifier,fragment_role
Guidance|SourceFragment|Requirements|Informative guidance, commentary or examples distinguished from mandatory provisions.|fragment_role
DrawingDetail|SourceFragment|Requirements|An identified project drawing detail with its drawing and revision identity.|fragment_identifier,revision_identifier
LegalProvision|SourceFragment|Requirements|A cited legal provision with jurisdiction/version and source; report opinions are not binding legal determinations.|jurisdiction,version_date,fragment_identifier
Requirement|DomainRecord|Requirements|A required outcome under an established source basis and assessment context.|requirement_identifier,requirement_basis,conditions,exceptions
PerformanceRequirement|Requirement|Requirements|A Performance Requirement considered in a compliance assessment.|requirement_basis
DTSProvision|Requirement|Requirements|A DTS provision considered separately from a Performance Requirement or documented Performance Solution.|requirement_basis
ComplianceAssessment|Assessment|Requirements|A finding/evidence assessment against considered requirements and a recorded compliance pathway.|compliance_pathway,assessment_purpose
ApplicabilityAssessment|Assessment|Editions and references|A context-specific supported, excluded or unresolved applicability decision using sourced facts and reviewed rules.|assessment_purpose,jurisdiction,conditions,exceptions
DefectItem|DomainRecord|Defects and assessments|An authored topic grouping that can contain distinct occurrences and explicitly shared reasoning.|recorded_name
DefectOccurrence|DomainRecord|Defects and assessments|A particular finding scoped to report/version/schedule, element and recorded location; repeated IDs are not merged automatically.|recorded_identifier,schedule_context,recorded_location
Observation|DomainRecord|Defects and assessments|What the source records at a finding or stated shared scope, retaining method and attribution.|recorded_text,observation_method
TestMeasurement|DomainRecord|Defects and assessments|A source reading, dimension or test with value, units, method, instrument and conditions as written; OCR remains uncertain.|value_as_written,units_as_written,measurement_method,instrument,measurement_date,conditions
ExpertAssessment|Assessment|Defects and assessments|An author's conclusion about a condition or departure with source-backed premises.|author_name,recorded_text
OccurrenceExtentAssessment|ExpertAssessment|Defects and assessments|An authored specific/recurring/systemic distribution assessment, separate from physical severity and statutory status.|recorded_text
StatusAssessment|ExpertAssessment|Defects and assessments|An authored major/non-major or other status with its cited basis and reasoning; element status alone is insufficient.|recorded_text,requirement_basis
SeverityAssessment|ExpertAssessment|Defects and assessments|A physical severity assessment, independent of occurrence extent and statutory major-defect status.|recorded_text
CauseAssessment|ExpertAssessment|Reasoning|An attributable confirmed, suspected, alternative or unresolved explanation; possible causes are not independently confirmed diagnoses.|recorded_text,causal_certainty,alternative_group
ConsequenceAssessment|ExpertAssessment|Reasoning|An attributable existing or predicted consequence, retaining the distinction from a failure's location.|recorded_text,consequence_kind
Reasoning|DomainRecord|Reasoning|The author's premises and reasoning connecting observations, history, construction and considered requirements.|recorded_text,author_name
ApplicationInference|Assessment|Reasoning|A later application inference with explicit premises, separate from report-authored reasoning.|recorded_text,premise_ids
RemediationOption|DomainRecord|Remediation|A source-authored proposed repair option with its scope, sequence, prerequisites, limitations and alternatives.|recorded_name,work_scope,alternative_group,limitations
RemediationScope|DomainRecord|Remediation|The source's complete repair scope and qualifications, including wider reinstatement alternatives.|recorded_text,limitations
RemediationStep|DomainRecord|Remediation|A source-listed proposed action in its authored order; a step is not evidence it was implemented.|sequence,recorded_text
Prerequisite|DomainRecord|Remediation|A source-stated condition such as design, consent, access, manufacturer confirmation or temporary accommodation.|prerequisite_kind,recorded_text
VerificationCriterion|DomainRecord|Remediation|An acceptance/verification criterion supplied by a source or separately reviewed proposal.|recorded_text
Party|DomainRecord|Parties|A named party with recorded identity; role or report proximity does not establish responsibility.|recorded_name
PartyRole|DomainRecord|Parties|A recorded builder, architect, certifier or waterproofer role, kept separate from a resolved named party.|role_name
Appointment|DomainRecord|Parties|A sourced appointment and scope linking a particular party to work or a project.|role_name,work_scope,relevant_dates
ResponsibilityAssessment|ExpertAssessment|Parties|An authored responsibility attribution with work scope, reasoning and source; distinct from physical cause or legal determination.|recorded_text,schedule_context
Authorship|DomainRecord|Parties|An attributable document/statement author identity and recorded date.|author_name,relevant_dates
OriginalAsset|DomainRecord|Evidence|Preserved original bytes identified by content hash, separately from every meaningful occurrence.|asset_hash,mime_type,byte_size
ImageAsset|OriginalAsset|Evidence|Original image bytes; identical bytes can be reused without merging occurrences or contexts.|asset_hash,mime_type,byte_size
ImageOccurrence|DomainRecord|Evidence|Where an image appears, its caption, source location, role and qualified finding/shared context.|image_role,caption,source_locator
DepictedFragment|DomainRecord|Evidence|The identified source fragment depicted by an image; identification is separate from original-source verification and applicability.|fragment_kind,fragment_identifier,printed_source_page
TextPassage|DomainRecord|Evidence|An exact anchored native or OCR source span, retaining offsets and content kind.|recorded_text,start_cp,end_cp,content_kind,source_locator
OCRExtraction|DomainRecord|Evidence|OCR output with regions, reading order, method and uncertainty; it cannot alone establish original governing text.|recorded_text,extraction_method,regions,reading_order
DiagramExtraction|DomainRecord|Evidence|Attributed labels, interfaces, dimensions and relationships extracted from an original diagram.|recorded_text,extraction_method,regions
ImageAnnotation|DomainRecord|Evidence|A highlight, arrow, crop or comment kept distinguishable from original source content.|annotation_kind,recorded_text
ReportedHistory|DomainRecord|Evidence|Attributable reported history, including instructed facts and repair accounts, distinct from direct observation.|recorded_text
LogicalUnit|DomainRecord|Evidence|A structural source grouping used to preserve occurrence or explicitly shared item context.|recorded_text,source_locator
EvidenceChunk|DomainRecord|Evidence|A searchable evidence revision with exact source segments; a chunk does not receive its own ontology.|content_kind,source_segments,source_locator
QualifiedAssertion|DomainRecord|Governance|A relation reified with subject, object, source spans, scope and independent evidence/review/verification/applicability/outcome dimensions.|predicate_id,subject_id,object_id
KnowledgeGap|DomainRecord|Governance|Missing, conflicting or unresolved evidence, distinguished from proof that a document or event does not exist.|gap_kind,recorded_text,source_availability
ReviewedRule|DomainRecord|Governance|An explicit sourced/versioned applicability or classification rule requiring reviewer and regression-case validation before activation.|rule_kind,jurisdiction,conditions,exceptions,reviewer,fixture_ids
SearchConcept|DomainRecord|Governance|A governed discovery term and aliases; similarity or alias matching cannot mint a factual cause, class or adoption link.|recorded_name,aliases
'''
# Predicate | domain alternatives | range alternatives | source group | meaning.
RELATIONS = '''
has_building|Project|Building|Context|A sourced project/building association.
has_part|Building|BuildingPart|Context|A sourced building/part association, without propagating classification.
has_location|DefectOccurrence,BuildingPart|Location|Context|The subject's recorded location, without deciding failure versus damage location.
concerns_element|DefectOccurrence,Assessment,DefectItem|BuildingElement|Context|A source-backed recorded or candidate element association.
element_at|BuildingElement|Location|Context|A specifically supported element/location link; not inferred from adjacent damage.
has_failure_location|CauseAssessment|Location|Reasoning|The sourced location of the proposed failure mechanism.
has_damage_location|ConsequenceAssessment|Location|Reasoning|The sourced location of consequential damage.
part_of_system|BuildingElement|ConstructionSystem|Context|A source-backed component/system relationship.
uses_material|BuildingElement,ConstructionSystem|Material|Context|A stated material association, retaining identification status.
uses_product|BuildingElement,ConstructionSystem|Product|Context|A stated product association; unknown products are not supplied.
has_interface|BuildingElement,Assessment|Interface|Context|A source-discussed junction/interface.
interface_between|Interface|BuildingElement|Context|The specifically identified elements participating in an interface.
has_use|BuildingPart,Building|BuildingUse|Context|A documented use; not a building-class inference.
has_condition|Assessment,BuildingElement,AssessmentContext|EnvironmentalCondition,ConstructionCondition|Context|A source-stated condition relevant to the scoped assessment.
has_classification_assessment|BuildingPart,Building|BuildingClassificationAssessment|Classification|A scoped classification assessment with source/context.
assesses_class|ClassificationAssessment|BuildingClass,ConcreteFinishClass,MembraneClass|Classification|A classification assessment of its stated kind; class families are disjoint.
uses_definition|ClassificationAssessment|ClassificationDefinition|Classification|The exact definition and exceptions considered.
definition_from|ClassificationDefinition|SourceFragment|Classification|Original source support for a classification definition.
has_work|Project,BuildingPart,BuildingElement|WorkEvent,WorkPackage,ProposedRemedialWork|Work and approvals|Affected work scope, distinguishing original, later and proposed work.
records_repair|DefectItem|RepairEvent|Remediation|Source-recorded repair history, never created from a recommendation.
has_history|DefectItem,Reasoning|ReportedHistory|Reasoning|Reported/instructed history retained with its attribution.
has_context|Assessment,ApplicabilityAssessment,WorkPackage|AssessmentContext|Work and approvals|The context and purpose of an assessment.
context_part|AssessmentContext|BuildingPart|Work and approvals|The particular building part in the context.
context_work|AssessmentContext|WorkPackage,WorkEvent,ProposedRemedialWork|Work and approvals|The relevant work and assessment purpose.
has_fact|AssessmentContext|ProjectFact|Work and approvals|A sourced/declarative fact retaining conflict and provenance.
has_approval_evidence|WorkPackage,AssessmentContext,SourceDocument|ApprovalRecord|Work and approvals|An approval/certification record or reported identity, preserving source availability.
records_inspection|SourceDocument,Assessment|InspectionRecord|Work and approvals|A recorded inspection and its scope/date.
documents_solution|ComplianceAssessment|PerformanceSolutionRecord|Requirements|A documented Performance Solution; absence of evidence is unresolved.
version_of|DocumentVersion|SourceDocument|Evidence|The source identity associated with an immutable version.
has_edition|CodeFamily,StandardFamily,StandardPart|CodeEdition,StandardEdition|Editions and references|A stated edition identity, separate from adoption or applicability.
has_standard_part|StandardFamily|StandardPart|Editions and references|A distinct part within a standard family.
has_volume|CodeEdition|CodeVolume|Editions and references|An edition-specific code volume identity.
has_jurisdiction_provision|CodeEdition|JurisdictionProvision|Editions and references|A separately sourced jurisdiction provision/variation.
contains_fragment|DocumentVersion,CodeEdition,CodeVolume,StandardEdition|SourceFragment,DepictedFragment|Requirements|A source fragment belongs to a specific identified document context.
fragment_parent|SourceFragment|SourceFragment|Requirements|Required parent provision or containing fragment context.
depends_on_fragment|SourceFragment,Requirement|SourceFragment|Requirements|A definition, header, note, condition or exception dependency.
cites_edition|ReportVersion,Reasoning,Assessment,DefectItem,DefectOccurrence|CodeEdition,StandardEdition,StandardFamily,StandardPart|Editions and references|A report citation with reported verification state, not automatic adoption.
has_reference_relationship|SourceFragment,Reasoning|ReferenceRelationship|Editions and references|A reported or verified scoped reference link with explicit basis.
references_source|ReferenceRelationship|CodeEdition,StandardEdition,DocumentVersion|Editions and references|The exact target identity, basis and amendments of a qualified reference relationship.
reference_origin|ReferenceRelationship|SourceFragment,CodeEdition,StandardEdition|Editions and references|The referencing provision and edition identity.
chain_contains|ReferenceChain|ReferenceRelationship|Editions and references|An independently assessed link in a primary/secondary/further chain.
expresses_requirement|SourceFragment|Requirement|Requirements|A required outcome under a stated basis and source role.
considers_requirement|ComplianceAssessment,Reasoning|Requirement,SourceFragment|Requirements|A considered requirement, without independently establishing applicability.
has_applicability_assessment|ComplianceAssessment,Requirement,AssessmentContext|ApplicabilityAssessment|Editions and references|A context-specific supported/excluded/unresolved evaluation.
decision_uses_rule|ApplicabilityAssessment,ClassificationAssessment|ReviewedRule|Governance|A reviewed, regression-validated rule considered by a decision.
contains_item|ReportVersion|DefectItem|Defects and assessments|An authored report topic grouping.
has_occurrence|DefectItem|DefectOccurrence|Defects and assessments|A finding explicitly scoped to its report item/version/schedule.
records_observation|DefectOccurrence,DefectItem|Observation|Defects and assessments|A specifically scoped observation, not proximity-based photo assignment.
has_measurement|Observation,DefectOccurrence,DefectItem,Reasoning|TestMeasurement|Defects and assessments|A value/reading as written with units and uncertainty, not an assumed moisture percentage.
has_assessment|DefectOccurrence,DefectItem|Assessment|Defects and assessments|An attributable assessment of the finding or shared item.
has_reasoning|DefectOccurrence,DefectItem,Assessment|Reasoning|Reasoning|The authored premises and reasoning in explicit occurrence/shared scope.
has_extent|DefectOccurrence,DefectItem|OccurrenceExtentAssessment|Defects and assessments|An authored distribution assessment, separate from severity/status.
has_status|DefectOccurrence,DefectItem|StatusAssessment|Defects and assessments|An authored major/non-major status and its source basis.
has_severity|DefectOccurrence,DefectItem|SeverityAssessment|Defects and assessments|A physical severity assessment, not statutory status.
has_cause_assessment|DefectOccurrence,DefectItem,Reasoning|CauseAssessment|Reasoning|An attributed confirmed/suspected/alternative/unresolved cause assessment.
has_consequence|DefectOccurrence,DefectItem,Reasoning|ConsequenceAssessment|Reasoning|An existing/predicted consequence with source certainty.
reasoning_premise|Reasoning,ApplicationInference|Observation,TestMeasurement,ReportedHistory,Requirement,SourceFragment|Reasoning|An explicitly sourced reasoning premise; application inference stays separate.
has_remediation|DefectOccurrence,DefectItem|RemediationOption|Remediation|A proposed source-authored repair option, not an undertaken event.
option_scope|RemediationOption|RemediationScope|Remediation|The complete scope, qualifications and source context of an option.
has_step|RemediationOption|RemediationStep|Remediation|A proposed action retained in its authored order.
has_prerequisite|RemediationOption,ProposedRemedialWork|Prerequisite|Remediation|A source-stated prerequisite applying to this option/work scope.
has_verification_criterion|RemediationOption,WorkPackage|VerificationCriterion|Remediation|An explicitly supplied or separately reviewed acceptance criterion.
alternative_to|RemediationOption|RemediationOption|Remediation|Explicit source alternatives kept separate with their own conditions.
proposes_work|RemediationOption|ProposedRemedialWork|Remediation|The proposed work scope, without asserting implementation.
mentions_party|ReportVersion,ResponsibilityAssessment|Party,PartyRole|Parties|A source-named party or role; generic roles do not resolve a particular party.
has_role|Party|PartyRole|Parties|A recorded role, separate from appointment and responsibility.
has_appointment|Party|Appointment|Parties|A sourced appointment/work scope.
has_responsibility|DefectOccurrence,DefectItem|ResponsibilityAssessment|Parties|An authored responsibility attribution, distinct from cause or binding liability.
assesses_responsibility|ResponsibilityAssessment|Party,PartyRole|Parties|The specifically named party or unresolved role being assessed.
has_authorship|DocumentVersion,Assessment,Reasoning|Authorship|Parties|The attributed author and recorded dates.
has_image_occurrence|ReportVersion,DocumentVersion|ImageOccurrence|Evidence|An image's structural occurrence in a document.
uses_asset|DocumentVersion,ImageOccurrence|OriginalAsset|Evidence|The preserved original bytes used by this version/occurrence.
has_visual_context|DefectItem|ImageOccurrence|Evidence|Explicitly shared item context, not evidence for every occurrence.
has_visual_evidence|DefectOccurrence,Assessment|ImageOccurrence|Evidence|A specifically sourced finding/assessment-to-image association.
depicts_fragment|ImageOccurrence|DepictedFragment|Evidence|A visible/caption/OCR fragment identity, separate from verification and applicability.
depiction_of|DepictedFragment|SourceFragment|Evidence|An independently matched original source fragment when verified.
has_ocr|ImageOccurrence|OCRExtraction|Evidence|OCR extraction with regions, reading order and uncertainty.
has_diagram_extraction|ImageOccurrence|DiagramExtraction|Evidence|Attributed diagram labels, dimensions or relationships.
has_annotation|ImageOccurrence|ImageAnnotation|Evidence|A separately identified annotation/crop/highlight.
has_passage|DocumentVersion|TextPassage|Evidence|A preserved exact source span with its locator/content kind.
contains_unit|DefectItem|LogicalUnit,Observation,Reasoning,Assessment,RemediationScope|Evidence|An explicit structural source grouping.
has_evidence_chunk|LogicalUnit,Observation,Reasoning,Assessment,RemediationScope|EvidenceChunk|Evidence|A search chunk supporting this source grouping.
chunk_supports|EvidenceChunk|QualifiedAssertion|Evidence|An exact source-span/shared-context mapping, not a similarity-generated fact.
supported_by|DomainRecord|TextPassage,ImageOccurrence,OriginalAsset|Governance|Source support with kind/scope/status retained.
has_gap|DomainRecord|KnowledgeGap|Governance|A scoped missing/conflicting/unresolved evidence gap, not proof of nonexistence.
mentions_concept|DomainRecord|SearchConcept|Governance|A governed discovery mapping that cannot mint causal/classification/adoption facts.
'''

STATUS_DIMENSIONS = {
    'statement_kind': ['recorded_observation','reported_history','author_opinion','user_declaration','original_source_text','application_inference','structural_document_membership','reported_reference','source_supported_mapping','ocr_extraction'],
    'review_state': ['extracted','uncertain','reviewed','superseded'],
    'source_identification': ['source_text','identifier_visible','caption_candidate','ocr_candidate','ambiguous','unknown'],
    'reference_verification': ['not_applicable','reported_only','embedded_extract_identified','original_source_matched','conflicting','unverified'],
    'applicability': ['supported','excluded','unresolved','not_assessed'],
    'repair_outcome': ['not_applicable','recommended','reported_undertaken','documented_outcome','outcome_unknown'],
    'certainty': ['source_recorded','author_attributed','suspected_or_alternative','unresolved'],
    'source_availability': ['imported','not_supplied','unresolved'],
}


def main():
    source = (ROOT / 'ONTOLOGY.md').read_text(encoding='utf-8')
    headings = [line[3:].strip() for line in source.splitlines() if line.startswith('## ')]
    classes=[]
    for row in CLASSES.strip().splitlines():
        cid,parent,group,definition,fields=row.split('|')
        classes.append({'id':cid,'label':re.sub(r'(?<=[a-z])(?=[A-Z])',' ',cid),
                        'parent':parent or None,'group':group,'definition':definition,'properties':fields.split(','),
                        'source_section':GROUPS[group]})
    class_ids={c['id'] for c in classes}
    relations=[]
    for row in RELATIONS.strip().splitlines():
        rid,domains,ranges,group,definition=row.split('|')
        domains,ranges=domains.split(','),ranges.split(',')
        assert set(domains+ranges)<=class_ids, rid
        relations.append({'id':rid,'label':rid.replace('_',' '),'domains':domains,'ranges':ranges,
                          'definition':definition,'source_section':GROUPS[group],
                          'requires_source':True,'requires_scope':True,'qualified':True})
    fields=sorted({field for c in classes for field in c['properties']})
    property_types={f:'string_or_unknown' for f in fields}
    for field in ['amendments','conditions','exceptions','aliases','premise_ids','fixture_ids','relevant_dates','source_segments','regions','reading_order']:
        property_types[field]='array_or_unknown'
    for field in ['sequence','start_cp','end_cp','byte_size']:
        property_types[field]='integer_or_unknown'
    model={'version':'building-defect-domain/1','source_document':'ONTOLOGY.md',
           'source_sha256':hashlib.sha256((ROOT/'ONTOLOGY.md').read_bytes()).hexdigest(),
           'classes':classes,'relationships':relations,'property_types':property_types,'status_dimensions':STATUS_DIMENSIONS,
           'disjoint_sets':[['BuildingClass','ConcreteFinishClass','MembraneClass'],['ImageAsset','ImageOccurrence','DepictedFragment'],['RemediationOption','RepairEvent']],
           'constraints':[
               {'id':'source_scope','rule':'Every factual relation has owned source spans/structural membership and explicit occurrence/item/context scope.'},
               {'id':'no_class_family_merging','rule':'Building, concrete finish and membrane class identifiers are not equivalent.'},
               {'id':'no_identifier_merging','rule':'Finding IDs are scoped to report/version/schedule; repeated identifiers produce review gaps, not automatic merges.'},
               {'id':'no_adoption_by_year','rule':'Publication/citation year alone never establishes adoption or applicability.'},
               {'id':'no_report_opinion_upgrade','rule':'Review does not change an authored opinion into an observation or binding legal determination.'},
               {'id':'original_rule_gate','rule':'Governing/classification decisions require original source support, reviewed rules and a specific assessment context.'},
               {'id':'no_recommendation_implementation','rule':'A remediation option/step cannot imply a repair was undertaken or effective.'},
               {'id':'no_ocr_authority_upgrade','rule':'OCR/image identification stays separate from original-source verification and applicability.'},
               {'id':'no_measurement_conversion','rule':'Keep source values and units; do not infer moisture percentages or resolve uncertain decimals.'},
               {'id':'no_generic_applies_to','rule':'Reference basis, edition/part/amendments, conditions and exceptions remain explicit.'},
               {'id':'no_similarity_facts','rule':'Similarity and alias matching produce discovery mappings, not causal, classification or adoption facts.'},
               {'id':'missing_not_nonexistent','rule':'Unavailable evidence is not proof a document or event does not exist.'},
           ],
           'source_coverage':[{'section':h,'covered_by': [c['id'] for c in classes if c['source_section']==h]+[r['id'] for r in relations if r['source_section']==h] or
                             {'Purpose and central concept':['Assessment','DefectOccurrence','concerns_element'],
                              'Relationship overview':['source_scope','contains_item','has_occurrence'],
                              'Code editions and volumes':['CodeEdition','CodeVolume','JurisdictionProvision'],
                              'Building the source library and graph':['EvidenceChunk','QualifiedAssertion','SearchConcept','ReviewedRule'],
                              'Sample basis and implementation boundaries':['source_scope','original_rule_gate']}.get(h,[])} for h in headings]}
    assert all(row['covered_by'] for row in model['source_coverage']), 'Uncovered specification section'
    output=ROOT/'knowledge/catalog/domain-model-v1.json'
    output.write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Compiled {len(classes)} domain classes, {len(relations)} typed relationships, {len(fields)} properties and {len(headings)} covered sections.')


if __name__=='__main__':
    main()
