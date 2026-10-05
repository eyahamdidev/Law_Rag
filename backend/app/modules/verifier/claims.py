"""Claim-support check.

A citation can be real while the passage still fails to support the sentence.
This module is where that split will be judged, then reviewed by people.
"""

from app.schemas.common import ModuleStatus, TraceStep


def check_claims(claims: list[str]) -> TraceStep:
    return TraceStep(
        module="verifier.claims",
        status=ModuleStatus.placeholder,
        detail=f"{len(claims)} claims waiting on a support check.",
    )
