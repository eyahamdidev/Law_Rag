"""Aid and financing match contract."""

from typing import Any, Literal
from pydantic import BaseModel, Field

from app.schemas.common import ModuleStatus, TraceStep
from app.schemas.agents import Citation, Claim


class AidProfile(BaseModel):
    """Founder profile used for program matching."""

    stage: Literal["idea", "creation", "extension", "growth", "unspecified"] = "unspecified"
    sector: str = ""
    need: Literal[
        "financing", "grant", "loan", "tax_incentive", "guarantee", "guidance", "unspecified"
    ] = "unspecified"
    funding_need_tnd: float | None = None
    employees: int | None = None
    governorate: str | None = None
    is_innovative: bool | None = None
    has_startup_label: bool | None = None
    is_graduate: bool | None = None
    free_text: str | None = None


class RuleTraceEntry(BaseModel):
    """Deterministic trace of one rule evaluation."""

    program_id: str
    step: Literal["stage", "sector", "size", "need", "conditions"]
    passed: bool
    criterion: str
    details: str


class DocumentChecklist(BaseModel):
    """Required documents and official form for a program."""

    program_id: str
    program_name: str
    required_documents: list[str] = Field(default_factory=list)
    official_form_link: str = ""


class Handoff(BaseModel):
    """Handoff contract when a user question concerns statutes/law."""

    to: Literal["law"] = "law"
    question: str


class AidProgram(BaseModel):
    """Structured funding or support program with provenance and conditions."""

    id: str
    name: str
    provider: str
    program_type: Literal["grant", "loan", "tax_incentive", "guarantee", "mixed"] = "grant"
    summary: str
    stages: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list, description="Eligible sectors. Empty means all sectors.")
    excluded_sectors: list[str] = Field(default_factory=list, description="Specifically excluded sectors.")
    max_employees: int | None = None
    min_employees: int | None = None
    max_investment_tnd: float | None = None
    min_investment_tnd: float | None = None
    requires_innovation: bool | None = False
    requires_label: bool | None = False
    requires_graduate: bool | None = False
    allowed_governorates: list[str] = Field(
        default_factory=list, description="Regional development zones (Groupe 1, Groupe 2, etc.)"
    )
    conditions: dict[str, Any] = Field(default_factory=dict)
    source_file: str = Field(default="", description="Source document in repository")
    source_page: int | None = Field(default=None, description="Page in source document")
    official_form_link: str = Field(default="", description="Link or relative path to official form")
    required_documents: list[str] = Field(default_factory=list)
    local_files: list[str] = Field(default_factory=list)


class AidMatchResponse(BaseModel):
    """Full deterministic match response with audit rule trace."""

    status: ModuleStatus
    programs: list[AidProgram] = Field(default_factory=list, description="Eligible matched programs")
    excluded_programs: list[dict[str, Any]] = Field(
        default_factory=list, description="Excluded programs with rejection reasons"
    )
    rule_trace: list[RuleTraceEntry] = Field(default_factory=list, description="Audit trace of all evaluated rules")
    document_checklists: list[DocumentChecklist] = Field(default_factory=list)
    handoff: Handoff | None = None
    summary: str
    trace: list[TraceStep] = Field(default_factory=list)
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    explanation_ref: str = ""
