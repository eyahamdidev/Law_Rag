"""Canonical view of founder facts: one schema over context.values + provenance.

The runtime store stays profile.Context (questionnaire / orchestrator / document).
This module validates and exposes the same fields for pipelines, tests, and APIs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.profile import Context
from app.questionnaire import BANK_BY_ID, SERIES_IDS

ProvenanceSource = Literal["questionnaire", "orchestrator", "document", "derived", "assumption"]

# User-facing labels in reports map orchestrator -> form-like wording where helpful.
PROVENANCE_LABEL = {
    "questionnaire": "form",
    "orchestrator": "form",
    "document": "upload",
    "derived": "calculation",
    "assumption": "assumption",
}


class PlanFacts(BaseModel):
    """All questionnaire field ids; only populated keys are set."""

    model_config = ConfigDict(extra="ignore")

    project_name: str | None = None
    stage: str | None = None
    sector: str | None = None
    legal_form: str | None = None
    startup_label: str | None = None
    governorate: str | None = None
    export_status: str | None = None
    share_capital: float | None = None
    years_in_operation: int | None = None
    problem: str | None = None
    solution: str | None = None
    differentiator: str | None = None
    target_customers: str | None = None
    market_size_note: str | None = None
    competitors: str | None = None
    pricing: str | None = None
    channels: str | None = None
    founders: str | None = None
    key_skills: str | None = None
    headcount: int | None = None
    avg_gross_salary: float | None = None
    production_means: str | None = None
    suppliers: str | None = None
    imported_share_pct: float | None = None
    capex_items: list[dict[str, Any]] | None = None
    total_investment: float | None = None
    funding_instrument: str | None = None
    funding_need_amount: float | None = None
    own_funds: float | None = None
    loan_amount: float | None = None
    loan_rate_pct: float | None = None
    loan_years: int | None = None
    grace_years: int | None = None
    grant_amount: float | None = None
    currency: str | None = None
    horizon_years: int | None = None
    revenue_by_year: list[float] | None = None
    cogs_by_year: list[float] | None = None
    payroll_by_year: list[float] | None = None
    opex_by_year: list[float] | None = None
    capex_by_year: list[float] | None = None
    tax_rate_pct: float | None = None
    last_revenue: float | None = None
    last_net_income: float | None = None
    extension_goal: str | None = None
    jobs_created: int | None = None
    impact_note: str | None = None
    risks: str | None = None
    traction_note: str | None = None
    ip_note: str | None = None
    awards_note: str | None = None
    permits_note: str | None = None

    provenance: dict[str, ProvenanceSource | str] = Field(default_factory=dict)

    @classmethod
    def from_context(cls, ctx: Context) -> PlanFacts:
        data = {k: v for k, v in ctx.values.items() if k in BANK_BY_ID}
        pf = cls.model_validate(data)
        pf.provenance = {k: ctx.provenance[k] for k in data if k in ctx.provenance}
        return pf

    def labelled_provenance(self) -> dict[str, str]:
        return {k: PROVENANCE_LABEL.get(str(v), str(v)) for k, v in self.provenance.items()}


def validate_context(ctx: Context) -> tuple[PlanFacts, dict[str, str]]:
    """Cross-field checks on merged facts. Does not mutate ctx; returns extra errors."""
    extra: dict[str, str] = {}
    pf = PlanFacts.from_context(ctx)
    h = ctx.values.get("horizon_years")
    if h is not None:
        try:
            n = int(h)
        except (TypeError, ValueError):
            extra["horizon_years"] = "must be 3 or 5"
            n = None
        if n is not None:
            for sid in SERIES_IDS:
                series = ctx.values.get(sid)
                if isinstance(series, list) and series and len(series) != n:
                    extra[sid] = f"expected {n} values for a {n}-year horizon, got {len(series)}"
    return pf, extra
