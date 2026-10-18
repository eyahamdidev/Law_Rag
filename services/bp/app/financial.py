"""Deterministic financial model and checker. No LLM touches a number here.

Two ways in: a table read from the uploaded plan, or the questionnaire's yearly
series. Both end up as the same ``FinancialModel``. Every derived figure is
recomputed in plain Python, and every assumption is written down in
``assumptions`` so the report can show it.

Thresholds below are rules of thumb used to say "review this". They are not
legal limits and not BFPME criteria. Tax rates must be confirmed against the
current finance law before anyone relies on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.contract import Evidence, Signal

DEFAULT_IS_RATE_PCT = 20.0  # general rate in the IS/IRPP code in the corpus (edition to LF 2024). Confirm for the current year.
DEFAULT_DEPRECIATION_YEARS = 5
TOL_REL = 0.01  # 1 percent
TOL_ABS = 1.0  # one dinar
GROWTH_REVIEW = 1.0  # +100 percent year over year
GROWTH_HIGH = 3.0  # +300 percent
# Early-stage pitch plans ramp from a pilot: the first step may be several times larger without being a red flag.
EARLY_FIRST_REVIEW, EARLY_FIRST_HIGH = 5.0, 14.0
EARLY_REVIEW, EARLY_HIGH = 2.5, 6.0
DSCR_REVIEW = 1.2
DSCR_HIGH = 1.0
PAYROLL_BAND = (0.95, 1.45)  # stated payroll / (headcount * avg gross * 12)


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class FinancialModel:
    years: list[str] = field(default_factory=list)
    revenue: list[float | None] = field(default_factory=list)
    cogs: list[float | None] = field(default_factory=list)
    payroll: list[float | None] = field(default_factory=list)
    opex: list[float | None] = field(default_factory=list)
    depreciation: list[float | None] = field(default_factory=list)
    interest: list[float | None] = field(default_factory=list)
    tax: list[float | None] = field(default_factory=list)
    capex: list[float | None] = field(default_factory=list)
    total_costs_stated: list[float | None] = field(default_factory=list)
    net_income_stated: list[float | None] = field(default_factory=list)
    debt_service_stated: list[float | None] = field(default_factory=list)
    uses: dict[str, float] = field(default_factory=dict)
    sources: dict[str, float] = field(default_factory=dict)
    uses_total_stated: float | None = None
    sources_total_stated: float | None = None
    loan_principal: float | None = None
    loan_rate_pct: float | None = None
    price_monthly: float | None = None  # price read from the answers when its period is stated
    price_period: str | None = None  # "month" | "year" | None (unknown periods never imply customers)
    loan_years: int | None = None
    grace_years: int = 0
    own_funds: float | None = None
    grant: float | None = None
    total_investment: float | None = None
    tax_rate_pct: float | None = None
    headcount: int | None = None
    avg_gross_salary: float | None = None
    evidence: dict[str, dict] = field(default_factory=dict)
    origin: str = "none"
    assumptions: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.years)

    def has_projection(self) -> bool:
        return any(v is not None for v in self.revenue)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _pad(values: list | None, n: int) -> list[float | None]:
    vals = [_f(v) for v in (values or [])][:n]
    return vals + [None] * (n - len(vals))


def from_answers(ctx_values: dict[str, Any]) -> FinancialModel:
    """Build a model from questionnaire answers (already normalised)."""
    v = ctx_values
    rev = v.get("revenue_by_year") or []
    n = int(v.get("horizon_years") or len(rev) or 0)
    m = FinancialModel(origin="questionnaire")
    if n:
        m.years = [f"Y{i + 1}" for i in range(n)]
        m.revenue = _pad(rev, n)
        m.cogs = _pad(v.get("cogs_by_year"), n)
        m.payroll = _pad(v.get("payroll_by_year"), n)
        m.opex = _pad(v.get("opex_by_year"), n)
        m.capex = _pad(v.get("capex_by_year"), n)
        m.depreciation = [None] * n
        m.interest = [None] * n
        m.tax = [None] * n
        m.total_costs_stated = [None] * n
        m.net_income_stated = [None] * n
        m.debt_service_stated = [None] * n
    m.loan_principal = _f(v.get("loan_amount"))
    m.loan_rate_pct = _f(v.get("loan_rate_pct"))
    m.loan_years = v.get("loan_years")
    pm = re.search(r"(\d+(?:[.,]\d+)?)", str(v.get("pricing") or ""))
    if pm:
        m.price_monthly = float(pm.group(1).replace(",", "."))
        low = str(v.get("pricing") or "").lower()
        m.price_period = "month" if re.search(r"month|mensu|mois|شهري|شهرة", low) else ("year" if re.search(r"year|annual|an\b|par an|سنوي", low) else None)
    m.grace_years = int(v.get("grace_years") or 0)
    m.own_funds = _f(v.get("own_funds"))
    m.grant = _f(v.get("grant_amount"))
    m.total_investment = _f(v.get("total_investment"))
    m.tax_rate_pct = _f(v.get("tax_rate_pct"))
    m.headcount = v.get("headcount")
    m.avg_gross_salary = _f(v.get("avg_gross_salary"))
    items = v.get("capex_items") or []
    if items:
        m.uses = {i["label"] or f"item {k + 1}": float(i["amount"]) for k, i in enumerate(items)}
    sources = {}
    if m.own_funds:
        sources["own_funds"] = m.own_funds
    if m.loan_principal:
        sources["loan"] = m.loan_principal
    if m.grant:
        sources["grant"] = m.grant
    m.sources = sources
    if m.total_investment is not None:
        m.uses_total_stated = m.total_investment
    return m


def merge_models(doc: FinancialModel, q: FinancialModel) -> FinancialModel:
    """Document figures win line by line. Questionnaire fills what the plan lacks."""
    if doc.origin == "none":
        return q
    if q.origin == "none":
        return doc
    out = FinancialModel(**{k: getattr(doc, k) for k in doc.__dict__})
    out.origin = "merged"
    n = out.n or q.n
    if not out.years:
        out.years, n = q.years, q.n
    for name in ("revenue", "cogs", "payroll", "opex", "depreciation", "interest", "tax", "capex",
                 "total_costs_stated", "net_income_stated", "debt_service_stated"):
        mine, theirs = _pad(getattr(out, name), n), _pad(getattr(q, name), n)
        merged = [a if a is not None else b for a, b in zip(mine, theirs)]
        setattr(out, name, merged)
    for name in ("loan_principal", "loan_rate_pct", "loan_years", "own_funds", "grant", "total_investment",
                 "tax_rate_pct", "headcount", "avg_gross_salary", "uses_total_stated"):
        if getattr(out, name) is None:
            setattr(out, name, getattr(q, name))
    if not out.uses:
        out.uses = q.uses
    if not out.sources:
        out.sources = q.sources
    out.assumptions = list(dict.fromkeys(doc.assumptions + q.assumptions))
    return out


# --------------------------------------------------------------------------------------
# derivation
# --------------------------------------------------------------------------------------

def loan_schedule(principal: float, rate_pct: float, years: int, grace: int = 0) -> list[dict]:
    """Annuity after an interest-only grace period. Returns one row per year."""
    rate = rate_pct / 100.0
    rows, bal = [], principal
    amort_years = max(years - grace, 1)
    pay = bal * rate / (1 - (1 + rate) ** -amort_years) if rate > 0 else bal / amort_years
    for y in range(1, years + 1):
        interest = bal * rate
        if y <= grace:
            princ = 0.0
        else:
            princ = min(pay - interest, bal)
        bal -= princ
        rows.append({"year": y, "interest": interest, "principal": princ, "service": interest + princ, "balance": bal})
    return rows


def derive(m: FinancialModel) -> dict:
    """Recompute the statements. Returns plain lists aligned to ``m.years``."""
    n = m.n
    z = lambda lst: [x or 0.0 for x in _pad(lst, n)]  # noqa: E731
    rev, cogs, pay, opex, capex = z(m.revenue), z(m.cogs), z(m.payroll), z(m.opex), z(m.capex)
    rate = m.tax_rate_pct if m.tax_rate_pct is not None else DEFAULT_IS_RATE_PCT
    if m.tax_rate_pct is None:
        note = f"Corporate tax rate: {DEFAULT_IS_RATE_PCT:g}% assumed (general rate in the IS code edition in the corpus). Confirm the current rate."
        if note not in m.assumptions:
            m.assumptions.append(note)

    # depreciation
    dep_given = [x for x in _pad(m.depreciation, n)]
    dep = [x or 0.0 for x in dep_given]
    if all(x is None for x in dep_given):
        base = m.total_investment or sum(m.uses.values()) or 0.0
        if base or any(capex):
            note = f"Depreciation: straight line over {DEFAULT_DEPRECIATION_YEARS} years on initial investment and yearly capex (assumption)."
            if note not in m.assumptions:
                m.assumptions.append(note)
            for t in range(min(n, DEFAULT_DEPRECIATION_YEARS)):
                dep[t] = base / DEFAULT_DEPRECIATION_YEARS
            # add yearly capex depreciation from the year after purchase
            for s in range(n):
                for t in range(s, min(n, s + DEFAULT_DEPRECIATION_YEARS)):
                    dep[t] += capex[s] / DEFAULT_DEPRECIATION_YEARS

    # loan
    sched = None
    interest = [x for x in _pad(m.interest, n)]
    principal_paid = [0.0] * n
    if m.loan_principal and m.loan_rate_pct is not None and m.loan_years:
        sched = loan_schedule(m.loan_principal, m.loan_rate_pct, int(m.loan_years), m.grace_years)
        for t in range(n):
            if t < len(sched):
                principal_paid[t] = sched[t]["principal"]
        if all(x is None for x in interest):
            interest = [sched[t]["interest"] if t < len(sched) else 0.0 for t in range(n)]
    interest = [x or 0.0 for x in interest]

    ebitda = [rev[t] - cogs[t] - pay[t] - opex[t] for t in range(n)]
    ebit = [ebitda[t] - dep[t] for t in range(n)]
    ebt = [ebit[t] - interest[t] for t in range(n)]
    given_tax = _pad(m.tax, n)
    tax = [given_tax[t] if given_tax[t] is not None else max(0.0, ebt[t]) * rate / 100.0 for t in range(n)]
    net = [ebt[t] - tax[t] for t in range(n)]

    inflow0 = (m.own_funds or 0.0) + (m.loan_principal or 0.0) + (m.grant or 0.0)
    spent0 = m.total_investment if m.total_investment is not None else (sum(m.uses.values()) or None)
    if spent0 is not None and inflow0:
        note = "Cash: initial funding is assumed spent on the stated total investment. Working-capital release is not modelled."
        if note not in m.assumptions:
            m.assumptions.append(note)
    cash, bal = [], (inflow0 - (spent0 or 0.0)) if inflow0 else 0.0
    for t in range(n):
        bal += net[t] + dep[t] - capex[t] - principal_paid[t]
        cash.append(bal)

    debt_service = [interest[t] + principal_paid[t] for t in range(n)]
    dscr = [((ebitda[t]) / debt_service[t]) if debt_service[t] > 0 else None for t in range(n)]
    fixed = [pay[t] + opex[t] + dep[t] + interest[t] for t in range(n)]
    cm = [((rev[t] - cogs[t]) / rev[t]) if rev[t] > 0 else None for t in range(n)]
    be_rev = [(fixed[t] / cm[t]) if cm[t] and cm[t] > 0 else None for t in range(n)]
    be_year = next((m.years[t] for t in range(n) if be_rev[t] is not None and rev[t] >= be_rev[t]), None)
    gross_margin = [((rev[t] - cogs[t]) / rev[t]) if rev[t] > 0 else None for t in range(n)]
    net_margin = [(net[t] / rev[t]) if rev[t] > 0 else None for t in range(n)]
    out = {
        "years": m.years, "revenue": rev, "cogs": cogs, "payroll": pay, "opex": opex, "capex": capex,
        "depreciation": dep, "interest": interest, "principal_paid": principal_paid, "tax": tax,
        "ebitda": ebitda, "ebit": ebit, "net_income": net, "cash_end": cash, "debt_service": debt_service,
        "dscr": dscr, "fixed_costs": fixed, "contribution_margin": cm, "break_even_revenue": be_rev,
        "break_even_year": be_year, "gross_margin": gross_margin, "net_margin": net_margin,
        "loan_schedule": sched, "tax_rate_pct": rate, "assumptions": list(m.assumptions),
    }
    # missing salaries or other costs: the profit, cash and break-even figures would silently count
    # those costs as zero, so they are withheld and the projection is marked incomplete.
    missing_costs = [name for name, lst in (("salaries", _pad(m.payroll, n)), ("other costs", _pad(m.opex, n)))
                     if all(x is None for x in lst)]
    if missing_costs and any(rev):
        note = ("Projection incomplete: " + " and ".join(missing_costs) + " not provided, so no profit or cash figure "
                "is computed; only revenue and direct margin are shown.")
        if note not in m.assumptions:
            m.assumptions.append(note)
        out["incomplete"], out["missing_costs"] = True, missing_costs
        out["assumptions"] = list(m.assumptions)
        for k in ("payroll", "opex", "tax", "ebitda", "ebit", "net_income", "cash_end", "debt_service",
                  "dscr", "fixed_costs", "break_even_revenue", "break_even_year", "net_margin"):
            out[k] = [None] * n if isinstance(out[k], list) else None
    if m.price_monthly is not None and m.price_period and any(rev):
        per = m.price_monthly * (12 if m.price_period == "month" else 1)
        out["implied_customers"] = [round(r / per, 1) if r and r > 0 else None for r in rev]
        unit = "month" if m.price_period == "month" else "year"
        note = f"Implied customers: revenue divided by a price of {m.price_monthly:g} per {unit} (read from your pricing answer)."
        if note not in m.assumptions:
            m.assumptions.append(note)
        out["assumptions"] = list(m.assumptions)
    return out


# --------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------

def _close(a: float, b: float, scale: float = 0.0) -> bool:
    return abs(a - b) <= max(TOL_ABS, TOL_REL * max(abs(a), abs(b), scale))


def _ev(m: FinancialModel, fieldname: str, value: Any, idx: int | None = None) -> Evidence:
    info = m.evidence.get(fieldname) or {}
    label = fieldname if idx is None or not m.years else f"{fieldname}[{m.years[idx]}]"
    return Evidence(field=label, value=value, page=info.get("page"), bbox=info.get("bbox"))


def _sig(kind: str, severity: str, message: str, ev: Evidence | None, tag: str = "") -> Signal:
    return Signal(id=f"bp-fin-{kind}{('-' + tag) if tag else ''}", kind=kind, severity=severity, message=message, evidence=ev, source="rule")


def check(m: FinancialModel, d: dict | None = None, early_stage: bool = False) -> list[Signal]:
    """Run every deterministic check. The wording is always 'review this'."""
    out: list[Signal] = []
    if not m.has_projection() and not m.uses and not m.sources:
        return out
    d = d or derive(m)
    n = m.n

    # 1. totals stated in the plan versus the plan's own lines
    tc = _pad(m.total_costs_stated, n)
    ni = _pad(m.net_income_stated, n)
    lines = [_pad(x, n) for x in (m.cogs, m.payroll, m.opex, m.depreciation, m.interest, m.tax)]
    rev = _pad(m.revenue, n)
    for t in range(n):
        parts = [ln[t] for ln in lines if ln[t] is not None]
        if tc[t] is not None and len(parts) >= 3 and not _close(tc[t], sum(parts), rev[t] or 0):
            out.append(_sig("sum_mismatch", "high",
                            f"Review this: stated total costs for {m.years[t]} ({tc[t]:,.0f}) differ from the sum of the cost lines ({sum(parts):,.0f}).",
                            _ev(m, "total_costs", tc[t], t), f"costs-{m.years[t]}"))
        if ni[t] is not None and rev[t] is not None:
            if tc[t] is not None:
                expected, basis = rev[t] - tc[t], "revenue minus stated total costs"
            elif len(parts) == 6:
                expected, basis = rev[t] - sum(parts), "revenue minus all cost lines"
            elif parts:
                # some cost lines are missing, so only an impossible result can be called out:
                # the net result cannot exceed revenue minus the costs that are shown.
                ceiling = rev[t] - sum(parts)
                if ni[t] > ceiling + max(TOL_ABS, TOL_REL * rev[t]):
                    out.append(_sig("sum_mismatch", "high",
                                    f"Review this: stated net result for {m.years[t]} ({ni[t]:,.0f}) is higher than revenue minus the cost lines shown ({ceiling:,.0f}).",
                                    _ev(m, "net_income", ni[t], t), f"net-{m.years[t]}"))
                continue
            else:
                continue
            if not _close(ni[t], expected, rev[t]):
                out.append(_sig("sum_mismatch", "high",
                                f"Review this: stated net result for {m.years[t]} ({ni[t]:,.0f}) does not match {basis} ({expected:,.0f}).",
                                _ev(m, "net_income", ni[t], t), f"net-{m.years[t]}"))

    # 2. funding table
    if m.uses and m.uses_total_stated is not None and not _close(sum(m.uses.values()), m.uses_total_stated):
        out.append(_sig("sum_mismatch", "high",
                        f"Review this: the investment lines add up to {sum(m.uses.values()):,.0f} but the plan states {m.uses_total_stated:,.0f}.",
                        _ev(m, "uses_total", m.uses_total_stated), "uses"))
    if m.sources and m.sources_total_stated is not None and not _close(sum(m.sources.values()), m.sources_total_stated):
        out.append(_sig("sum_mismatch", "high",
                        f"Review this: the funding sources add up to {sum(m.sources.values()):,.0f} but the plan states {m.sources_total_stated:,.0f}.",
                        _ev(m, "sources_total", m.sources_total_stated), "sources"))
    uses_total = m.uses_total_stated if m.uses_total_stated is not None else (sum(m.uses.values()) or None)
    sources_total = m.sources_total_stated if m.sources_total_stated is not None else (sum(m.sources.values()) or None)
    if uses_total is not None and sources_total is not None and not _close(uses_total, sources_total):
        gap = sources_total - uses_total
        out.append(_sig("sources_neq_uses", "high",
                        f"Review this: sources of funds ({sources_total:,.0f}) and uses of funds ({uses_total:,.0f}) differ by {abs(gap):,.0f}"
                        f" ({'sources exceed uses' if gap > 0 else 'uses exceed sources'}).",
                        _ev(m, "sources_total", sources_total), ""))

    # 3. impossible values
    for t in range(n):
        if rev[t] is not None and rev[t] < 0:
            out.append(_sig("impossible_margin", "high", f"Review this: negative revenue in {m.years[t]}.", _ev(m, "revenue", rev[t], t), f"rev-{m.years[t]}"))
        gm, nm = d["gross_margin"][t], d["net_margin"][t]
        cg = _pad(m.cogs, n)[t]
        if gm is not None and cg is not None and (gm > 1.0 or gm < 0):
            out.append(_sig("impossible_margin", "review",
                            f"Review this: gross margin in {m.years[t]} is {gm:.0%}"
                            f"{' (direct costs exceed revenue)' if gm < 0 else ''}.",
                            _ev(m, "cogs", cg, t), f"gm-{m.years[t]}"))
        has_costs = any(x is not None and x != 0 for x in (_pad(m.cogs, n)[t], _pad(m.payroll, n)[t], _pad(m.opex, n)[t]))
        if nm is not None and nm > 0.6 and has_costs:
            out.append(_sig("impossible_margin", "review",
                            f"Review this: net margin in {m.years[t]} is {nm:.0%}, which is unusually high. Check costs are complete.",
                            _ev(m, "net_income", d["net_income"][t], t), f"nm-{m.years[t]}"))

    # 4. growth plausibility
    for t in range(1, n):
        a, b = rev[t - 1], rev[t]
        if a and b is not None and a > 0:
            g = b / a - 1
            hi, rv = (GROWTH_HIGH, GROWTH_REVIEW) if not early_stage else ((EARLY_FIRST_HIGH, EARLY_FIRST_REVIEW) if t == 1 else (EARLY_HIGH, EARLY_REVIEW))
            if g >= hi:
                out.append(_sig("growth_implausible", "high", f"Review this: revenue grows {g:.0%} from {m.years[t-1]} to {m.years[t]}. Say what drives it.", _ev(m, "revenue", b, t), m.years[t]))
            elif g >= rv:
                out.append(_sig("growth_implausible", "review", f"Review this: revenue grows {g:.0%} from {m.years[t-1]} to {m.years[t]}. Say what drives it.", _ev(m, "revenue", b, t), m.years[t]))

    # 5. cash
    if m.has_projection() and d.get("cash_end") and d["cash_end"][0] is not None:
        first_neg = next((t for t, c in enumerate(d["cash_end"]) if c < -TOL_ABS), None)
        if first_neg is not None:
            out.append(_sig("negative_cash", "high",
                            f"Review this: modelled cash falls to {d['cash_end'][first_neg]:,.0f} at the end of {m.years[first_neg]}. "
                            "Check the financing plan or the cost lines.",
                            _ev(m, "cash_end", d["cash_end"][first_neg], first_neg), m.years[first_neg]))

    # 6. debt service
    for t in range(n):
        s = d["dscr"][t]
        if s is None:
            continue
        if s < DSCR_HIGH:
            out.append(_sig("dscr_low", "high", f"Review this: operating profit before depreciation covers {s:.2f}x of the loan payments in {m.years[t]}. Under 1.0x means the payments are not covered.",
                            _ev(m, "dscr", round(s, 2), t), m.years[t]))
        elif s < DSCR_REVIEW:
            out.append(_sig("dscr_low", "review", f"Review this: debt-service cover is {s:.2f}x in {m.years[t]}. Lenders often look for more than {DSCR_REVIEW}x. Confirm the bank's own threshold.",
                            _ev(m, "dscr", round(s, 2), t), m.years[t]))

    # 7. stated debt service versus the loan terms
    ds = _pad(m.debt_service_stated, n)
    sched = d["loan_schedule"]
    if sched:
        for t in range(min(n, len(sched))):
            if ds[t] is not None and not _close(ds[t], sched[t]["service"], 0) and abs(ds[t] - sched[t]["service"]) > 0.05 * max(sched[t]["service"], 1):
                out.append(_sig("loan_schedule_mismatch", "review",
                                f"Review this: stated loan payment for {m.years[t]} is {ds[t]:,.0f}; the stated terms give about {sched[t]['service']:,.0f}.",
                                _ev(m, "debt_service", ds[t], t), m.years[t]))

    # 8. tax
    if m.tax_rate_pct is None and not d.get("incomplete"):
        tx = _pad(m.tax, n)
        for t in range(n):
            ebt = d["ebit"][t] - d["interest"][t]
            if tx[t] is not None and ebt > 0 and not _close(tx[t] / ebt * 100, DEFAULT_IS_RATE_PCT, 0) and abs(tx[t] / ebt * 100 - DEFAULT_IS_RATE_PCT) > 2:
                out.append(_sig("tax_rate_mismatch", "info",
                                f"Review this: the tax in {m.years[t]} is {tx[t] / ebt:.0%} of pre-tax profit; the general rate used here is {DEFAULT_IS_RATE_PCT:g}%. Confirm the rate that applies to the activity this year.",
                                _ev(m, "tax", tx[t], t), m.years[t]))
    # 9. payroll versus headcount and wage
    if m.headcount and m.avg_gross_salary:
        base = m.headcount * m.avg_gross_salary * 12
        pay = _pad(m.payroll, n)
        for t in range(n):
            if pay[t] is not None and base > 0:
                ratio = pay[t] / base
                if t == 0 and not (PAYROLL_BAND[0] <= ratio <= PAYROLL_BAND[1]):
                    out.append(_sig("payroll_inconsistent", "review",
                                    f"Review this: payroll in {m.years[t]} is {pay[t]:,.0f}. {m.headcount} people at {m.avg_gross_salary:,.0f} gross a month is {base:,.0f} before social charges, a ratio of {ratio:.2f}.",
                                    _ev(m, "payroll", pay[t], t), m.years[t]))
    # 10. break-even
    if m.has_projection() and any(x for x in rev if x) and not d.get("incomplete"):
        if d["break_even_year"] is None:
            out.append(_sig("no_break_even", "review", "Review this: revenue does not reach the break-even level within the projection horizon.",
                            _ev(m, "revenue", rev[-1] if rev else None, n - 1 if n else None), ""))
    return out
