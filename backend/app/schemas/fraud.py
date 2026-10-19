"""Fraud-signal contract.

The module reports review signals on a document the user uploaded.
It does not declare that a document is legally fraudulent.
"""

from pydantic import BaseModel, Field

from app.schemas.common import ModuleStatus, TraceStep


class FraudAnalyzeMeta(BaseModel):
    mode: str = Field(
        default="stamp",
        description="stamp (PDF/image + organization id) or payment (JSON or document → /v1/score)",
    )
    entity_id: str | None = Field(
        default=None,
        description="Organization key for stamp verification (document.entity_id)",
    )


class FraudSignal(BaseModel):
    code: str
    description: str
    severity: str


class FraudEnrollmentPrompt(BaseModel):
    kind: str
    proposal_id: str
    preview_base64: str | None = None
    title: str
    subtitle: str = "Future uploads will be compared to what you save here."


class FraudDecideResult(BaseModel):
    proposal_id: str
    enrolled: bool
    decision: str | None = None
    reason: str | None = None
    tenant_secret: str | None = None
    message: str


class FraudStampSpecimen(BaseModel):
    specimen_id: str
    comment: str = ""
    read_text: str = ""
    created_at: str = ""
    preview_base64: str | None = None


class FraudStampGallery(BaseModel):
    entity_id: str
    stamps: list[FraudStampSpecimen] = Field(default_factory=list)
    locked: bool = False
    message: str = ""


class FraudReport(BaseModel):
    status: ModuleStatus
    filename: str
    document_type: str  # stamp | payment (historical field name)
    document_hash: str
    risk_level: str
    risk_score: int | None = None
    stamp_verdict: str | None = None
    headline: str = ""
    signals: list[FraudSignal]
    summary: str
    enrollments: list[FraudEnrollmentPrompt] = Field(default_factory=list)
    trace: list[TraceStep]
