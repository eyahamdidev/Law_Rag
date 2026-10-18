"""PlanFacts schema and cross-field validation."""

from app.plan_facts import PlanFacts, validate_context
from app.profile import Context, merge_context


def test_plan_facts_from_merged_context():
    ctx = merge_context(None, {"project_name": "Polaris", "horizon_years": "5",
                               "revenue_by_year": "20000, 60000, 150000, 300000, 500000"}, None)
    pf = PlanFacts.from_context(ctx)
    assert pf.project_name == "Polaris"
    assert pf.horizon_years == 5
    assert len(pf.revenue_by_year or []) == 5
    assert pf.provenance.get("project_name") == "questionnaire"


def test_horizon_series_length_mismatch():
    ctx = merge_context(None, {"horizon_years": "5", "revenue_by_year": "100, 200, 300"}, None)
    _, extra = validate_context(ctx)
    assert "revenue_by_year" in extra
