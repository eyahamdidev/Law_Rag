"""Filter the local catalog by stage.

This is not an eligibility decision. Sector and need are echoed for the
later rules engine and are not applied yet.
"""

from app.modules.aid.catalog import CATALOG
from app.schemas.aid import AidMatchResponse, AidProfile
from app.schemas.common import ModuleStatus, TraceStep


def match(profile: AidProfile) -> AidMatchResponse:
    if profile.stage == "unspecified":
        programs = list(CATALOG)
        detail = "No stage selected, so the full local catalog is listed."
    else:
        programs = [item for item in CATALOG if profile.stage in item.stages]
        detail = f"Filtered the catalog to stage={profile.stage}."

    sector = profile.sector.strip() or "unspecified"
    return AidMatchResponse(
        status=ModuleStatus.placeholder,
        programs=programs,
        summary=(
            "These entries match the company stage against files already in "
            "the repository. Eligibility, sector rules, and amounts are not "
            f"applied yet (sector: {sector}, need: {profile.need}). "
            "Confirm every program on the publisher's current form."
        ),
        trace=[
            TraceStep(module="aid.matcher", status=ModuleStatus.ok, detail=detail),
            TraceStep(
                module="aid.eligibility",
                status=ModuleStatus.placeholder,
                detail="Rules for sector, size, and incentive amounts are not encoded.",
            ),
        ],
    )
