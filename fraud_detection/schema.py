from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LabelType(str, Enum):
    """Separate supervision targets. These must not be collapsed into one label."""

    CARD_FRAUD = "CARD_FRAUD"
    AML_LAUNDERING = "AML_LAUNDERING"
    ACCOUNT_TAKEOVER = "ACCOUNT_TAKEOVER"
    INVOICE_FRAUD = "INVOICE_FRAUD"
    EXPENSE_FRAUD = "EXPENSE_FRAUD"
    PROCUREMENT_RISK = "PROCUREMENT_RISK"
    ANOMALY = "ANOMALY"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Decision(str, Enum):
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"


class Transaction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transaction_id: str
    timestamp: datetime
    amount: float = Field(ge=0)
    currency: str = "TND"
    transaction_type: str = "transfer"
    sender_id: str
    receiver_id: str
    sender_name: str | None = None
    receiver_name: str | None = None
    sender_kind: str | None = None
    receiver_kind: str | None = None
    channel: str | None = None
    country_from: str | None = None
    country_to: str | None = None
    merchant_category: str | None = None
    description: str | None = None
    invoice_id: str | None = None
    expense_id: str | None = None
    device_id: str | None = None
    old_balance: float | None = None
    new_balance: float | None = None
    declared_annual_revenue: float | None = None
    company_age_days: int | None = None
    company_status: str | None = None
    bid_count: int | None = None
    award_to_estimate_ratio: float | None = None
    submission_window_days: int | None = None
    dataset: str | None = None
    label_type: LabelType | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_id: str
    name: str
    kind: str = "company"
    country: str = "TN"
    governorate: str | None = None
    activity: str | None = None
    registered_on: datetime | None = None
    status: str = "active"
    declared_annual_revenue: float | None = None
    is_pep: bool = False
    lei: str | None = None


class SanctionsEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    list_name: str
    entity_type: str = "entity"
    programs: list[str] = Field(default_factory=list)


class Signal(BaseModel):
    signal: str
    severity: Severity
    label_types: list[LabelType] = Field(default_factory=list)
    detail: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ModelScores(BaseModel):
    supervised: float | None = None
    anomaly: float | None = None
    graph: float | None = None
    supervised_by_type: dict[str, float] = Field(default_factory=dict)
    anomaly_source: str | None = None
    general_behavior: float | None = None
    specialist_sources: dict[str, str] = Field(default_factory=dict)


class ExternalChecks(BaseModel):
    sanctions: bool = False
    entity_verified: bool = False
    sanctions_lists: list[str] = Field(default_factory=list)
    sanctions_status: str = "not_available"
    matched_list: str | None = None
    matched_entity: str | None = None
    match_score: float | None = None


class SignalView(BaseModel):
    signal: str
    severity: str
    detail: str


class TunisiaLayer(BaseModel):
    """Tunisia routing result. tunisia_score stays null until real labeled transactions exist."""

    country: str | None = None
    country_detection: str = "not_tunisian"
    coverage: str = "NOT_APPLICABLE"
    global_score: float | None = None
    tunisia_score: float | None = None
    anomaly_score: float | None = None
    sanctions_score: float | None = None
    rule_score: float | None = None
    final_score: int | None = None
    risk_label: str | None = None
    specialist: str | None = None
    explanations: list[str] = Field(default_factory=list)
    data_sources_used: list[str] = Field(default_factory=list)
    model_trained: bool = False
    model_status: str = "not_applicable"
    context: dict[str, Any] = Field(default_factory=dict)


class DocumentMark(BaseModel):
    kind: str
    page: int | None = None
    status: str
    similarity: float | None = None
    specimen_id: str | None = None
    differences: list[str] = Field(default_factory=list)
    proposal_id: str | None = None
    crop_base64: str | None = None
    question: str | None = None
    verdict: str | None = None
    genuine_probability: float | None = None
    comment: str | None = None
    read_text: str | None = None
    enrolled_text: str | None = None
    alignment_ncc: float | None = None
    review_reason: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    review_recommended: bool = False
    risk_level: str = "medium"


class DocumentReview(BaseModel):
    """Stamp and signature review for a file sent with a score. Null when no file was sent."""

    checked: bool
    source: str
    pages: int
    warnings: list[str] = Field(default_factory=list)
    approval_required: bool = False
    marks: list[DocumentMark] = Field(default_factory=list)
    proof: bool = False
    text_excerpt: str | None = None
    note: str = ""
    forensics: dict[str, Any] = Field(default_factory=dict)


class FraudAssessment(BaseModel):
    risk_score: int
    decision: Decision
    fraud_types: list[str]
    label_types: list[str]
    signals: list[SignalView]
    model_scores: ModelScores
    external_checks: ExternalChecks
    confidence: float
    requires_human_review: bool
    explanation: str
    risk_level: str = ""
    evidence: list[str] = Field(default_factory=list)
    entity_checks: dict[str, Any] = Field(default_factory=dict)
    data_coverage: str = "MEDIUM"
    model_confidence: float = 0.5
    graph_status: str = "insufficient_history"
    tunisia: TunisiaLayer = Field(default_factory=TunisiaLayer)
    documents: DocumentReview | None = None
