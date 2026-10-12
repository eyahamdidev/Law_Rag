"""Wire contract (spec section 2.2), vendored for the bp service.

The shared ``contracts/`` package is owned by P5. Until it is published this
file mirrors section 2.2 field for field. When ``contracts==X.Y`` exists, replace
the body of this module with ``from contracts import *`` and pin the version.

Do not add fields here. Business-plan specific data travels in ``options``
(request) and in a ``json`` artifact labelled ``bp_report`` (response).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0.0-bp-vendored"

Lang = Literal["fr", "ar", "en"]
Workspace = Literal["law", "fraud", "aid", "bp"]
Status = Literal["ok", "abstain", "error"]
Severity = Literal["info", "review", "high"]
ErrorCode = Literal["BAD_INPUT", "UNSUPPORTED_FILE", "MODEL_UNAVAILABLE", "TIMEOUT", "INTERNAL"]


class Request(BaseModel):
    request_id: str
    workspace: Workspace = "bp"
    lang: Lang = "fr"
    question: str | None = None
    file_ref: str | None = None
    profile: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    trace_parent: str | None = None


class Citation(BaseModel):
    doc_id: str
    passage_id: str
    code_or_title: str
    article: str | None = None
    page: int | None = None
    bbox: list[float] | None = None
    version_date: str | None = None
    publication_date: str | None = None
    effective_date: str | None = None
    score: float = 0.0
    score_kind: Literal["relevance", "rerank", "rule"] = "relevance"


class Evidence(BaseModel):
    field: str
    value: Any = None
    page: int | None = None
    bbox: list[float] | None = None


class Signal(BaseModel):
    id: str
    kind: str
    severity: Severity
    message: str  # always "review this" wording, never an accusation
    evidence: Evidence | None = None
    source: Literal["rule", "model", "both"] = "rule"


class Artifact(BaseModel):
    kind: Literal["png", "docx", "xlsx", "json"]
    file_ref: str
    label: str


class Handoff(BaseModel):
    to: Workspace
    question: str


class TraceStep(BaseModel):
    step: str
    ms: int = 0
    model: str | None = None
    prompt_id: str | None = None  # "<prompt_id>@<version>"


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str


class Response(BaseModel):
    request_id: str
    module: str = "bp"
    status: Status
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    handoff: Handoff | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    latency_ms: int = 0
    error: ErrorInfo | None = None


class ModuleError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
