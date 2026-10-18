"""Filter and evaluate Tunisian aid and financing programs via deterministic rules.

The rules engine deterministically checks stage, sector, size, need, and
specific program constraints. The LLM does not make eligibility rulings.
"""

from app.modules.aid.rules_engine import match_programs
from app.schemas.aid import AidMatchResponse, AidProfile
from app.schemas.common import ModuleStatus, TraceStep


def match(profile: AidProfile) -> AidMatchResponse:
    """Run deterministic rule engine matching on a founder profile."""
    result = match_programs(profile)
    eligible = result["eligible_programs"]
    excluded = result["excluded_programs"]
    rule_trace = result["rule_trace"]
    checklists = result["document_checklists"]
    handoff = result["handoff"]

    n_eligible = len(eligible)
    n_excluded = len(excluded)

    stage_desc = profile.stage if profile.stage != "unspecified" else "any stage"
    sector_desc = profile.sector if profile.sector else "any sector"
    need_desc = profile.need if profile.need != "unspecified" else "any financial instrument"

    summary = (
        f"Evaluated {n_eligible + n_excluded} programs for stage='{stage_desc}', "
        f"sector='{sector_desc}', need='{need_desc}'. "
        f"Identified {n_eligible} eligible programs and excluded {n_excluded} programs based on deterministic criteria."
    )

    trace = [
        TraceStep(
            module="aid.rules_engine.stage",
            status=ModuleStatus.ok,
            detail=f"Evaluated stage eligibility for profile stage '{stage_desc}'.",
        ),
        TraceStep(
            module="aid.rules_engine.sector",
            status=ModuleStatus.ok,
            detail=f"Checked sector constraints and exclusions for '{sector_desc}'.",
        ),
        TraceStep(
            module="aid.rules_engine.size_and_need",
            status=ModuleStatus.ok,
            detail=f"Checked size limits and need alignment for '{need_desc}'.",
        ),
        TraceStep(
            module="aid.rules_engine.provenance",
            status=ModuleStatus.ok,
            detail=f"Attached official document checklists and provenance citations for {n_eligible} matched programs.",
        ),
    ]

    if handoff:
        trace.append(
            TraceStep(
                module="aid.handoff",
                status=ModuleStatus.ok,
                detail=f"Statute question detected: handed off to {handoff.to}.",
            )
        )

    return AidMatchResponse(
        status=ModuleStatus.ok,
        programs=eligible,
        excluded_programs=excluded,
        rule_trace=rule_trace,
        document_checklists=checklists,
        handoff=handoff,
        summary=summary,
        trace=trace,
    )
