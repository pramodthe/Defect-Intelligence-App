from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class Locator(BaseModel):
    document_version_id: str
    format: Literal["docx", "pdf"]
    xml_part: str | None = None
    xpath: str | None = None
    paragraph_ordinal: int | None = None
    table_path: list[int] = Field(default_factory=list)
    relationship_id: str | None = None
    page_index: int | None = None
    printed_page_label: str | None = None
    rotation: int = 0
    raw_bbox: list[float] | None = None
    normalized_bbox: list[float] | None = None
    page_box: list[float] | None = None
    source_printed_page: str | None = None
    heading_path: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_format(self):
        if self.format == "docx" and (not self.xml_part or not self.xpath):
            raise ValueError("Word locators require actual XML part and XPath")
        if self.format == "pdf" and (self.page_index is None or self.page_index < 0):
            raise ValueError("PDF locators require a nonnegative page index")
        if self.normalized_bbox and not all(0 <= v <= 1 for v in self.normalized_bbox):
            raise ValueError("Invalid normalized PDF bounds")
        return self


class SourceBlock(BaseModel):
    block_id: str
    document_version_id: str
    parent_block_id: str | None = None
    kind: str
    order_key: list[int]
    text: str = ""
    extraction_kind: str = "native_text"
    locator: Locator
    payload: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DocumentIR(BaseModel):
    schema_version: str = "document-ir/1"
    document_version_id: str
    structure_revision_id: str
    original_asset_id: str
    parser_profile_id: str
    root_block_ids: list[str]
    blocks: list[SourceBlock]
    asset_ids: list[str]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ownership(self):
        ids = {b.block_id for b in self.blocks}
        if len(ids) != len(self.blocks):
            raise ValueError("Duplicate block identity")
        for b in self.blocks:
            if b.document_version_id != self.document_version_id:
                raise ValueError("Foreign document block")
            if b.parent_block_id and b.parent_block_id not in ids:
                raise ValueError("Missing parent")
            seen = {b.block_id}
            parent = b.parent_block_id
            by_id = {x.block_id: x for x in self.blocks}
            while parent:
                if parent in seen:
                    raise ValueError("Cyclic structure")
                seen.add(parent)
                parent = by_id[parent].parent_block_id
        return self


class Segment(BaseModel):
    block_id: str
    start_cp: int = Field(ge=0)
    end_cp: int = Field(gt=0)
    role: Literal["body", "header_context", "overlap", "note_context"] = "body"


class ChunkMetadata(BaseModel):
    schema_version: str = "chunk/1"
    chunk_id: str
    chunk_revision_id: str
    document_version_id: str
    structure_revision_id: str
    semantic_revision_id: str
    annotation_revision_id: str | None = None
    logical_unit_id: str
    parent_context_id: str
    source_role: str
    authority_role: str
    content_kind: str
    section_path: list[str]
    section_purpose: str
    defect_item_id: str | None = None
    occurrence_ids: list[str] = Field(default_factory=list)
    option_id: str | None = None
    media_occurrence_ids: list[str] = Field(default_factory=list)
    concept_ids: list[str] = Field(default_factory=list)
    assertion_ids: list[str] = Field(default_factory=list)
    cited_reference_ids: list[str] = Field(default_factory=list)
    identified_reference: dict[str, Any] = Field(default_factory=dict)
    source_segments: list[Segment]
    dependency_ids: list[str] = Field(default_factory=list)
    token_count: int
    tokenizer_profile: str
    chunker_profile_id: str = "structure-bge/1"
    extraction_review_state: str = "extracted"
    warnings: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    kind: Literal["report_excerpt", "report_author_reasoning", "prior_recommendation", "inference", "governing"]
    anchor_ids: list[str]
    quote: str | None = None
    decision_id: str | None = None
    edition_id: str | None = None
    building_class: str | None = None
    fragment_id: str | None = None
    draft_section: Literal["observation", "requirements", "assessment", "opinion", "recommendation"] | None = None


class DraftAnswer(BaseModel):
    claims: list[Claim]
    gaps: list[str] = Field(default_factory=list)
    selected_media_ids: list[str] = Field(default_factory=list)


class EvidenceGrade(BaseModel):
    sufficient: bool
    missing: list[str] = Field(default_factory=list)
    next_queries: list[str] = Field(default_factory=list, max_length=3)


class ClarificationQuestion(BaseModel):
    key: str
    question: str


class DeclaredFact(BaseModel):
    key: str
    value: str
    evidence_quote: str


class ClarificationPlan(BaseModel):
    sufficient: bool
    message: str
    questions: list[ClarificationQuestion] = Field(default_factory=list, max_length=3)
    extracted_facts: list[DeclaredFact] = Field(default_factory=list)


class AssertionCandidate(BaseModel):
    subject_id: str
    predicate: str
    object_id: str | None = None
    value: str
    kind: Literal["recorded_observation", "reported_history", "author_opinion", "reported_reference"]
    scope: str
    anchor_ids: list[str]
    quotations: list[str]


class DomainCandidates(BaseModel):
    assertions: list[AssertionCandidate]
    warnings: list[str] = Field(default_factory=list)


class FactResponse(BaseModel):
    expected_context_version: int
    facts: dict[str, str] = Field(default_factory=dict)
    message: str = Field(default="", max_length=4000)
    provenance: str = Field(min_length=3)


class QuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    mode: Literal["draft", "historical", "current", "remedial", "comparison"] = "draft"
    project_id: str | None = None
    part_id: str | None = None
    context_version: int | None = None
    client_request_id: str = Field(min_length=8, max_length=150)


class Rule(BaseModel):
    id: str
    version: int
    kind: Literal["edition", "classification", "reference", "provision"]
    jurisdiction: str
    purpose: str
    predicates: dict[str, Any]
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
    effect: dict[str, Any]
    source_anchor_ids: list[str]
    fixture_ids: list[str]
    fixture_results: dict[str, bool] = Field(default_factory=dict)
    reviewer: str | None = None
    state: Literal["draft", "active", "superseded"] = "draft"
    synthetic: bool = False
    fixture_cases: list[dict[str, Any]] = Field(default_factory=list)


class EditionReview(BaseModel):
    document_id: str
    family: str
    part: str | None = None
    year: str = Field(pattern=r"^(19|20)\d{2}$")
    volume: str | None = None
    amendments: list[str]
    reviewer: str = Field(min_length=3)
    anchor_ids: list[str] = Field(min_length=1)
    synthetic: bool = False


class FragmentReview(BaseModel):
    edition_id: str
    kind: Literal["clause", "figure", "table", "definition", "note", "appendix"]
    identifier: str
    anchor_ids: list[str] = Field(min_length=1)
    dependency_ids: list[str] = Field(default_factory=list)


class ReferenceReview(BaseModel):
    from_fragment_id: str
    to_edition_id: str
    basis: Literal["primary", "secondary", "project_specification", "informative"]
    scope: str = Field(min_length=3)
    predicates: dict[str, Any]
    anchor_ids: list[str] = Field(min_length=1)
    reviewer: str = Field(min_length=3)
