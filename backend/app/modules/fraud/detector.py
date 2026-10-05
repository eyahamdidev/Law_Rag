"""Accept a document, hash it, and stop.

Scoring is intentionally not implemented. The upload is not written to disk.
Labelled samples for a later model belong in fraud_detection/.
"""

import hashlib

from app.modules.intake.extractor import inspect_document
from app.schemas.common import ModuleStatus, TraceStep
from app.schemas.fraud import FraudReport


def analyze_upload(filename: str, content: bytes, document_type: str) -> FraudReport:
    digest = hashlib.sha256(content).hexdigest()
    intake = inspect_document(filename or "upload", len(content))
    return FraudReport(
        status=ModuleStatus.placeholder,
        filename=filename or "upload",
        document_type=document_type,
        document_hash=digest,
        risk_level="unknown",
        signals=[],
        summary=(
            "The file was received and hashed. Fraud scoring is not connected, "
            "so there is no risk level. Planned checks look for missing fiscal "
            "identifiers, inconsistent dates, duplicate files, and totals that "
            "do not match the lines. A person reviews every signal. This module "
            "will not declare a document legally fraudulent."
        ),
        trace=[
            intake,
            TraceStep(
                module="fraud.detector",
                status=ModuleStatus.placeholder,
                detail=f"SHA-256 {digest[:12]}… stored only in this response.",
            ),
        ],
    )
