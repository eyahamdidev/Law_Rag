"""Public contracts for the legal feature; independent of the other teams' APIs."""
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.agents import AgentResult, Attachment, FounderProfile

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
TermText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
Language = Literal["fr", "ar", "en"]


class GuidanceRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    language: Language = "fr"
    jurisdiction: ShortText = "Tunisia"
    profile: FounderProfile = Field(default_factory=FounderProfile)
    attachments: list[Attachment] = Field(default_factory=list, max_length=3)

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Please provide a legal question")
        return value.strip()

    @field_validator("attachments")
    @classmethod
    def bounded_attachments(cls, items):
        if sum(len(item.text) for item in items) > 40000:
            raise ValueError("Attachment text exceeds 40,000 characters")
        return items


class ChecklistRequest(BaseModel):
    task: Literal["startup_label", "company_creation", "patent", "trademark", "copyright"]
    language: Language = "fr"
    jurisdiction: ShortText = "Tunisia"
    profile: FounderProfile = Field(default_factory=FounderProfile)


class GuidanceResponse(BaseModel):
    result: AgentResult
    mode: Literal["grounded_answer", "evidence_only", "needs_info", "abstained"]
    jurisdiction: str
    research_links: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ShortText = ""
    address: ShortText = ""
    role: ShortText = ""


class EquityAllocation(BaseModel):
    party: ShortText
    percentage: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_type: str = Field(min_length=1, max_length=50)
    language: Language = "fr"
    jurisdiction: ShortText = ""
    effective_date: date | None = None
    parties: list[Party] = Field(default_factory=list, max_length=12)
    purpose: TermText = ""
    terms: dict[ShortText, TermText] = Field(default_factory=dict, max_length=30)
    equity: list[EquityAllocation] = Field(default_factory=list, max_length=12)
    profile: FounderProfile = Field(default_factory=FounderProfile)
    attachments: list[Attachment] = Field(default_factory=list, max_length=3)
    refine_with_llm: bool = True
    export_docx: bool = False

    @field_validator("attachments")
    @classmethod
    def bounded_context(cls, attachments):
        if sum(len(item.text) for item in attachments) > 40000:
            raise ValueError("Attachment text exceeds 40,000 characters")
        return attachments


class MissingField(BaseModel):
    field: str
    question: str


class DraftClause(BaseModel):
    id: str
    title: str
    text: str


class DraftResponse(BaseModel):
    status: Literal["needs_info", "draft_for_review"]
    contract_type: str
    language: Language
    title: str
    template_version: str = "2026-10-16.v1"
    template_origin: str = "Project-authored drafting aid; not a jurisdiction-approved legal form"
    mode: Literal["intake", "template", "llm_refined"] = "intake"
    missing_fields: list[MissingField] = Field(default_factory=list)
    clauses: list[DraftClause] = Field(default_factory=list)
    review_points: list[str] = Field(default_factory=list)
    source_documents: list[str] = Field(default_factory=list)
    source_citations: list[dict] = Field(default_factory=list)
    document_text: str = ""
    docx_base64: str | None = None
    filename: str | None = None


class ExtractedDocument(BaseModel):
    attachment: Attachment
    needs_ocr_pages: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
