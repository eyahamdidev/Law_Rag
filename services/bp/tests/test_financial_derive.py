"""Financial derive() checked against independent formulas (no LLM)."""

from app.financial import FinancialModel, check, derive, from_answers


def test_ebitda_when_costs_complete():
    m = FinancialModel(years=["Y1", "Y2"], revenue=[100_000.0, 180_000.0], cogs=[30_000.0, 50_000.0],
                       payroll=[40_000.0, 45_000.0], opex=[10_000.0, 12_000.0], origin="questionnaire")
    d = derive(m)
    assert not d.get("incomplete")
    assert d["ebitda"][0] == 100_000 - 30_000 - 40_000 - 10_000
    assert d["net_income"][0] == d["ebitda"][0] - d["depreciation"][0] - d["tax"][0]


def test_incomplete_when_payroll_missing():
    m = from_answers({"horizon_years": "3", "revenue_by_year": [50_000, 400_000, 3_000_000],
                      "cogs_by_year": [5_000, 20_000, 100_000]})
    d = derive(m)
    assert d["incomplete"]
    assert d["net_income"] == [None, None, None]
    margin0 = (50_000 - 5_000) / 50_000
    assert abs(d["gross_margin"][0] - margin0) < 1e-6


def test_zero_cogs_is_not_missing():
    m = from_answers({"horizon_years": "3", "revenue_by_year": [10, 20, 30], "cogs_by_year": [0, 0, 0],
                      "payroll_by_year": [1, 2, 3], "opex_by_year": [1, 1, 1]})
    d = derive(m)
    assert not d.get("incomplete")


def test_implied_customers_monthly_pricing():
    m = from_answers({"horizon_years": "1", "revenue_by_year": [120_000], "pricing": "10 TND per month",
                      "payroll_by_year": [50_000], "opex_by_year": [10_000], "cogs_by_year": [20_000]})
    d = derive(m)
    assert d.get("implied_customers") == [1000.0]  # 120k annual / (10*12) per customer-year at 10/month


def test_implied_customers_annual_pricing():
    m = from_answers({"horizon_years": "1", "revenue_by_year": [500], "pricing": "500 TND per year",
                      "payroll_by_year": [100], "opex_by_year": [50], "cogs_by_year": [50]})
    d = derive(m)
    assert d.get("implied_customers") == [1.0]


def test_no_implied_customers_when_period_unknown():
    m = from_answers({"horizon_years": "1", "revenue_by_year": [1000], "pricing": "500 TND",
                      "payroll_by_year": [100], "opex_by_year": [50], "cogs_by_year": [50]})
    d = derive(m)
    assert "implied_customers" not in d


def test_sources_neq_uses_signal():
    m = FinancialModel(uses={"equipment": 80_000}, sources={"own_funds": 40_000, "loan": 30_000},
                       uses_total_stated=80_000, sources_total_stated=70_000, years=["Y1"], revenue=[10_000.0],
                       payroll=[5_000.0], opex=[2_000.0], cogs=[1_000.0], origin="questionnaire")
    sigs = check(m, derive(m))
    assert any(s.kind == "sources_neq_uses" for s in sigs)


def test_chat_and_upload_same_financials_when_facts_match():
    from app import pipeline as pl
    from app.contract import Request
    from app.profile import merge_context
    from app import financial as fin

    answers = {"project_name": "X", "horizon_years": "3", "revenue_by_year": "100, 200, 300",
               "cogs_by_year": "10, 20, 30", "payroll_by_year": "40, 40, 40", "opex_by_year": "5, 5, 5"}
    ctx = merge_context(None, answers, {"revenue_by_year": [100, 200, 300]})
    m = fin.from_answers(ctx.values)
    d = fin.derive(m)
    assert not d.get("incomplete")
    assert d["revenue"] == [100.0, 200.0, 300.0]
