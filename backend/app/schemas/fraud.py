"""Fraud-signal contract.

The module reports review signals on a document the user uploaded.
It does not declare that a document is legally fraudulent.
"""

from pydantic import BaseModel, Field

from app.schemas.common import ModuleStatus, TraceStep


class FraudAnalyzeMeta(BaseModel):
    document_type: str = Field(
        default="invoice",
        description="invoice, bank_statement, financing_application, or business_plan",
    )


class FraudSignal(BaseModel):
    code: str
    description: str
    severity: str


class FraudReport(BaseModel):
    status: ModuleStatus
    filename: str
    document_type: str
    document_hash: str
    risk_level: str
    signals: list[FraudSignal]
    summary: str
    trace: list[TraceStep]
