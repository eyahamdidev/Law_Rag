"""Compare a plan with the reference data from the pack. Always "review this", never "wrong".

Each comparison carries the source, the region and a verified flag. US sector margins are a
rough yardstick, not a Tunisian norm, and the message says so.
"""

from __future__ import annotations

from app import knowledge as kb
from app.contract import Evidence, Signal

MARGIN_SLACK_ABS = 0.15  # plan margin must exceed the benchmark by this much...
MARGIN_SLACK_REL = 1.0  # ...and by this multiple of the benchmark before we say anything
LOAN_RATE_GAP = 1.5  # points below the TMM before a loan rate looks low


def _sig(kind: str, severity: str, msg: str, field: str, value=None) -> Signal:
    return Signal(id=f"bp-bench-{kind}", kind=kind, severity=severity, message=msg, evidence=Evidence(field=field, value=value), source="rule")


def run(model, derived: dict | None, values: dict) -> tuple[list[Signal], dict]:
    signals: list[Signal] = []
    report: dict = {"sector": None, "parameters_used": [], "country_risk": kb.tunisia_country_risk(), "notes": []}
    used = report["parameters_used"]

    def use(key: str) -> dict | None:
        p = kb.param(key)
        if p:
            used.append({"key": key, **p})
        return p

    # ---- sector margin ------------------------------------------------------------
    sector = values.get("sector")
    industry = kb.industry_for(sector)
    if sector and industry is None:
        report["notes"].append(f"No sector benchmark matched '{sector}'. Name the activity in plainer words to get one.")
    if industry and kb.benchmarks_available():
        bm = kb.industry_benchmark(industry)
        report["sector"] = {"asked": sector, "matched_industry": industry, "benchmark": bm}
        if bm and derived and derived.get("revenue"):
            rate = (derived.get("tax_rate_pct") or 20.0) / 100
            worst = None
            for t, (rev, ebit) in enumerate(zip(derived["revenue"], derived["ebit"])):
                if rev and rev > 0 and ebit is not None:
                    margin = ebit * (1 - rate if ebit > 0 else 1) / rev
                    if worst is None or margin > worst[1]:
                        worst = (derived["years"][t], margin)
            b = bm["after_tax_operating_margin"]
            report["sector"]["plan_best_margin"] = None if worst is None else {"year": worst[0], "after_tax_operating_margin": worst[1]}
            if worst and worst[1] > b + max(MARGIN_SLACK_ABS, MARGIN_SLACK_REL * abs(b)):
                signals.append(_sig(
                    "margin_above_sector", "review",
                    f"Review this: the plan reaches an after-tax operating margin of {worst[1]:.0%} in {worst[0]}. "
                    f"The reference for '{industry}' is {b:.0%} ({bm['region']} firms, {bm['as_of']}, Damodaran). "
                    "That is US data, a rough yardstick and not a Tunisian norm. Explain what makes this plan different.",
                    "margin", round(worst[1], 3)))

    # ---- loan rate versus the money-market rate --------------------------------------
    tmm = use("tmm_pct")
    rate = getattr(model, "loan_rate_pct", None)
    if tmm and rate is not None and rate < tmm["value"] - LOAN_RATE_GAP:
        signals.append(_sig(
            "loan_rate_low", "review",
            f"Review this: the loan rate of {rate:g}% is below the money-market rate (TMM about {tmm['value']:g}%, {tmm['as_of']}, {tmm['source']}). "
            "Bank loans to firms usually sit above it. This may be fine for a subsidised line; say which one.",
            "loan_rate_pct", rate))

    # ---- stated tax rate versus the IS code ------------------------------------------
    is_rate, reduced = use("is_general_rate_pct"), use("is_reduced_rates_pct")
    stated = getattr(model, "tax_rate_pct", None)
    if is_rate and stated is not None:
        ok = {is_rate["value"], *(reduced["value"] if reduced else [])}
        if not any(abs(stated - r) < 0.01 for r in ok) and stated != 0:
            signals.append(_sig(
                "tax_rate_unusual", "info",
                f"Review this: the plan uses a corporate tax rate of {stated:g}%. The general rate in the IS code is {is_rate['value']:g}% "
                f"({is_rate['source']}); reduced rates exist for some activities. Confirm which applies.",
                "tax_rate_pct", stated))

    # ---- employer social charges ----------------------------------------------------
    export = str(values.get("export_status") or "")
    key = "cnss_employer_rate_exporting_pct" if export == "total" else "cnss_employer_rate_general_pct"
    cnss = use(key)
    hc, sal = getattr(model, "headcount", None), getattr(model, "avg_gross_salary", None)
    if cnss and hc and sal and model.payroll and model.payroll[0]:
        ratio = model.payroll[0] / (hc * sal * 12)
        if 0.95 <= ratio < 1.10:
            signals.append(_sig(
                "payroll_without_charges", "info",
                f"Review this: the payroll is about {ratio:.2f}x gross salaries, so it may leave out employer social charges "
                f"(CNSS employer rate about {cnss['value']:g}%, {cnss['source']}; not verified against the official text). Check whether they are included.",
                "payroll", round(ratio, 3)))
    unverified = [u["key"] for u in used if not u.get("verified")]
    if unverified:
        report["notes"].append("These parameters come from secondary sources and must be confirmed before they are quoted: " + ", ".join(sorted(set(unverified))))
    return signals, report
