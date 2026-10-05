"""Deterministic citation checks.

Confirm the document id exists, the page is inside the PDF, and the article
identifier was stored at ingestion. A model is not the source of this check.
"""

from app.schemas.chat import Citation
from app.schemas.common import ModuleStatus, TraceStep


def check_citations(citations: list[Citation]) -> TraceStep:
    if not citations:
        return TraceStep(
            module="verifier.citations",
            status=ModuleStatus.placeholder,
            detail="No citations to check.",
        )
    return TraceStep(
        module="verifier.citations",
        status=ModuleStatus.placeholder,
        detail="Citation checks are not connected.",
    )
