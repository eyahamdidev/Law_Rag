"""Seeded synthetic business plans with injected faults (spec: about 30 plans with financial errors).

``valid_model`` builds a plan that should raise no review or high signal. Each
injector breaks exactly one thing and names the signal kind that must fire.
"""

from __future__ import annotations

import copy
import random

FAULTS = ["sum_mismatch", "sources_neq_uses", "impossible_margin", "growth_implausible",
          "negative_cash", "dscr_low", "loan_schedule_mismatch", "payroll_inconsistent", "no_break_even"]
EXPECT = {f: f for f in FAULTS}


def valid_model(rng: random.Random) -> dict:
    """Plain dict in the shape of financial.FinancialModel fields, three years."""
    n = 3
    headcount, salary = rng.randint(3, 6), rng.randint(1100, 1800)
    payroll = [round(headcount * salary * 12 * 1.2 * (1 + 0.04 * i)) for i in range(n)]
    rev1 = payroll[0] / rng.uniform(0.18, 0.26)
    growth = [1.0, rng.uniform(1.25, 1.55), rng.uniform(1.2, 1.4)]
    rev, r = [], rev1
    for g in growth:
        r *= g
        rev.append(round(r))
    cogs = [round(x * rng.uniform(0.30, 0.38)) for x in rev]
    opex = [round(x * rng.uniform(0.08, 0.12)) for x in rev]
    capex_total = rng.randint(80, 160) * 1000
    loan = round(capex_total * rng.uniform(0.25, 0.4), -3)
    grant = 0
    own = capex_total - loan
    years = rng.choice([4, 5])
    return {
        "years": ["Y1", "Y2", "Y3"], "revenue": rev, "cogs": cogs, "payroll": payroll, "opex": opex,
        "capex": [0.0, 0.0, 0.0], "loan_principal": float(loan), "loan_rate_pct": rng.choice([8.0, 9.5, 11.0]),
        "loan_years": years, "grace_years": 0, "own_funds": float(own), "grant": float(grant),
        "total_investment": float(capex_total), "uses": {"equipment": float(capex_total)},
        "sources": {"own_funds": float(own), "loan": float(loan)}, "headcount": headcount, "avg_gross_salary": float(salary),
    }


def inject(m: dict, fault: str, rng: random.Random) -> dict:
    m = copy.deepcopy(m)
    if fault == "sum_mismatch":
        m["total_costs_stated"] = [round((m["cogs"][t] + m["payroll"][t] + m["opex"][t]) * 0.7) for t in range(3)]
        m["cogs_lines_extra"] = True  # marker for the generator: three lines + stated total below their sum
        m["depreciation"] = [1000.0] * 3
    elif fault == "sources_neq_uses":
        m["sources"]["own_funds"] += m["total_investment"] * 0.2
    elif fault == "impossible_margin":
        m["cogs"][0] = round(m["revenue"][0] * 1.3)
    elif fault == "growth_implausible":
        m["revenue"][1] = m["revenue"][0] * 5
    elif fault == "negative_cash":
        m["own_funds"] = m["total_investment"] * 0.1
        m["loan_principal"] = 0.0
        m["sources"] = {"own_funds": m["own_funds"]}
        m["payroll"] = [x * 3 for x in m["payroll"]]
        m["headcount"] = None
    elif fault == "dscr_low":
        m["loan_principal"] = m["total_investment"] * 6
        m["loan_rate_pct"] = 12.0
        m["loan_years"] = 3
        m["own_funds"] = 0.0
        m["sources"] = {"loan": m["loan_principal"]}
        m["total_investment"] = m["loan_principal"]
        m["uses"] = {"equipment": m["loan_principal"]}
    elif fault == "loan_schedule_mismatch":
        m["debt_service_stated"] = [1000.0, 1000.0, 1000.0]
    elif fault == "payroll_inconsistent":
        m["payroll"] = [x * 2.4 for x in m["payroll"]]
    elif fault == "no_break_even":
        m["revenue"] = [x * 0.25 for x in m["revenue"]]
    return m


def to_model(d: dict):
    from app.financial import FinancialModel

    keys = {k: v for k, v in d.items() if k in FinancialModel.__dataclass_fields__}
    m = FinancialModel(**keys)
    m.origin = "synthetic"
    n = len(m.years)
    for name in ("depreciation", "interest", "tax", "total_costs_stated", "net_income_stated", "debt_service_stated"):
        if not getattr(m, name):
            setattr(m, name, [None] * n)
    return m


def dataset(seed: int = 7, n_fault: int = 30, n_valid: int = 20) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n_fault):
        fault = FAULTS[i % len(FAULTS)]
        rows.append({"id": f"f{i + 1:03d}", "fault": fault, "model": inject(valid_model(rng), fault, rng)})
    for i in range(n_valid):
        rows.append({"id": f"v{i + 1:03d}", "fault": None, "model": valid_model(rng)})
    return rows


# ---------------------------------------------------------------------------- section mapping set
ALT_HEADINGS = {
    "executive_summary": ["Aperçu général", "Le projet en bref"],
    "promoters_team": ["Qui sommes-nous", "Les porteurs du projet"],
    "project_description": ["Notre offre", "Le produit et sa valeur"],
    "market_analysis": ["Notre environnement commercial", "Clients et concurrents"],
    "marketing_plan": ["Stratégie de vente", "Prix et distribution"],
    "operations": ["Organisation de la production", "Fournisseurs et locaux"],
    "human_resources": ["Équipe et recrutements", "Effectifs prévus"],
    "legal_structure": ["Cadre juridique", "Statut et capital"],
    "investment_plan": ["Besoins d'investissement", "Équipements à acquérir"],
    "financing_plan": ["Comment financer le projet", "Ressources financières"],
    "financial_projections": ["Chiffres prévisionnels", "Rentabilité attendue"],
    "risks": ["Ce qui peut mal tourner", "Menaces et parades"],
}
BODY = {
    "executive_summary": "Ce projet propose un service à des cliniques et demande un financement pour démarrer l'activité.",
    "promoters_team": "Le fondateur a dix ans d'expérience dans le domaine et dirige l'équipe comme gérant.",
    "project_description": "Le problème des clients est la perte de temps. Notre solution est un service simple, avec un avantage unique.",
    "market_analysis": "La clientèle cible est composée de cliniques. Le marché compte des concurrents établis et une concurrence locale.",
    "marketing_plan": "Le prix est fixé par abonnement. La vente passe par un canal direct et des réseaux sociaux.",
    "operations": "Les équipements et le local sont loués. Le fournisseur principal livre le matériel chaque mois.",
    "human_resources": "L'effectif de départ est de quatre salariés avec un salaire moyen défini, recrutement progressif.",
    "legal_structure": "La forme juridique est une SARL avec un capital réparti entre deux associés.",
    "investment_plan": "L'investissement comprend un équipement, des immobilisations et un besoin en fonds de roulement.",
    "financing_plan": "Le financement combine fonds propres, un crédit et une subvention, avec des emplois et ressources équilibrés.",
    "financial_projections": "Le chiffre d'affaires et le résultat sont prévus sur trois ans, avec la trésorerie et le seuil de rentabilité.",
    "risks": "Le principal risque est le retard de paiement; la mesure d'atténuation est un acompte à la commande.",
}


def plan_text(rng: random.Random, present: list[str]) -> tuple[str, dict[str, str]]:
    """Return (plain text, expected mapping heading -> section id)."""
    lines, truth = [], {}
    for sid in present:
        h = rng.choice(ALT_HEADINGS[sid])
        lines += [h, BODY[sid], ""]
        truth[h] = sid
    return "\n".join(lines), truth
