"""Generate templates/*.json (BFPME creation, BFPME extension, GIZ).

IMPORTANT: the official model files (Modele_Business_Plan_Creation.xls,
Modele_Business_Plan_Extension.xls, Modele_Plan_Affaires_GIZ.doc) are legacy
Office formats and were not readable when this skeleton was written. The section
list below is a standard business-plan structure aligned with the headings those
models are known to use. Every template therefore carries
``"verified_against_official_model": false`` and ``source_page: null``.
Once the official files are converted to .xlsx/.docx, check the headings and
flip the flag per template. Run:  python scripts/build_templates.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "templates"


def crit(cid, en, fr, kw_fr, kw_en, kw_ar=(), number=False):
    return {
        "id": cid,
        "text": {"en": en, "fr": fr},
        "keywords": {"fr": list(kw_fr), "en": list(kw_en), "ar": list(kw_ar)},
        "needs_number": number,
    }


def sec(sid, en, fr, ar, kw_fr, kw_en, kw_ar, criteria, questions, required=True, weight=1.0):
    return {
        "id": sid,
        "title": {"en": en, "fr": fr, "ar": ar},
        "title_keywords": {"fr": kw_fr, "en": kw_en, "ar": kw_ar},
        "required": required,
        "weight": weight,
        "criteria": criteria,
        "questions": questions,
    }


COMMON = [
    sec("executive_summary", "Executive summary", "Résumé du projet", "ملخص المشروع",
        ["résumé", "synthèse", "présentation du projet", "executive"], ["executive summary", "summary", "overview"],
        ["ملخص", "نبذة"],
        [crit("c_what", "States what the business does", "Dit ce que fait l'entreprise",
              ["activité", "produit", "service", "projet"], ["business", "product", "service", "project"]),
         crit("c_need", "States the amount and use of funds", "Indique le montant et l'usage des fonds",
              ["financement", "investissement", "montant", "dt", "tnd"], ["funding", "investment", "amount", "tnd", "dt"], number=True)],
        ["project_name", "solution", "total_investment"]),
    sec("promoters_team", "Promoters and team", "Promoteurs et équipe", "المبعوثون والفريق",
        ["promoteur", "équipe", "fondateur", "porteur"], ["founder", "team", "promoter", "management"],
        ["باعث", "فريق", "مؤسس"],
        [crit("c_exp", "Describes founders' experience", "Décrit l'expérience des promoteurs",
              ["expérience", "diplôme", "formation", "parcours"], ["experience", "background", "degree", "career"]),
         crit("c_roles", "Assigns roles", "Répartit les rôles",
              ["rôle", "responsable", "directeur", "gérant"], ["role", "responsible", "manager", "ceo", "cto"])],
        ["founders", "key_skills"]),
    sec("project_description", "Project, offer and value proposition", "Description du projet et de l'offre", "وصف المشروع والعرض",
        ["description du projet", "offre", "produit", "service", "proposition de valeur", "idée"],
        ["project description", "offer", "value proposition", "product", "solution"],
        ["وصف المشروع", "العرض", "المنتج"],
        [crit("c_problem", "Names the customer problem", "Nomme le problème client",
              ["problème", "besoin", "difficulté"], ["problem", "need", "pain"]),
         crit("c_solution", "Explains the solution", "Explique la solution",
              ["solution", "offre", "produit", "service"], ["solution", "offer", "product", "service"]),
         crit("c_diff", "States what makes it different", "Indique ce qui le différencie",
              ["différenc", "avantage", "innov", "unique"], ["different", "advantage", "innovat", "unique"])],
        ["problem", "solution", "differentiator"]),
    sec("market_analysis", "Market and competition", "Étude de marché et concurrence", "دراسة السوق والمنافسة",
        ["marché", "concurren", "clientèle", "cible", "étude de marché"], ["market", "competitor", "competition", "customers", "target"],
        ["السوق", "منافس", "حرفاء"],
        [crit("c_target", "Defines target customers", "Définit la clientèle cible",
              ["cible", "clientèle", "segment", "client"], ["target", "customer", "segment"]),
         crit("c_size", "Sizes the market with a figure and a source", "Chiffre le marché avec une source",
              ["taille du marché", "part de marché", "ins", "source", "étude"], ["market size", "market share", "source", "survey"], number=True),
         crit("c_comp", "Names competitors", "Nomme les concurrents",
              ["concurrent", "concurrence"], ["competitor", "competition", "alternative"])],
        ["target_customers", "market_size_note", "competitors"]),
    sec("marketing_plan", "Marketing and sales", "Plan marketing et commercial", "الخطة التسويقية",
        ["marketing", "commercial", "prix", "tarif", "distribution", "vente"], ["marketing", "sales", "pricing", "price", "channel", "distribution"],
        ["تسويق", "أسعار", "توزيع"],
        [crit("c_price", "States pricing", "Indique les prix",
              ["prix", "tarif", "dt"], ["price", "pricing", "tnd", "dt"], number=True),
         crit("c_channel", "Describes sales channels", "Décrit les canaux de vente",
              ["canal", "distribution", "vente", "réseaux"], ["channel", "distribution", "sales", "online"])],
        ["pricing", "channels"]),
    sec("operations", "Operations and production", "Moyens de production et exploitation", "الاستغلال والإنتاج",
        ["production", "exploitation", "moyens", "fournisseur", "local", "équipement", "approvisionnement"],
        ["operations", "production", "supplier", "premises", "equipment", "supply"],
        ["الإنتاج", "الاستغلال", "المزودين", "المعدات"],
        [crit("c_means", "Lists equipment and premises", "Liste les équipements et locaux",
              ["équipement", "local", "machine", "matériel"], ["equipment", "premises", "machine", "facility"]),
         crit("c_supply", "Names suppliers or supply chain", "Nomme les fournisseurs",
              ["fournisseur", "approvisionnement", "matières"], ["supplier", "supply", "raw material"])],
        ["production_means", "suppliers", "imported_share_pct", "governorate"]),
    sec("human_resources", "Organisation and human resources", "Organisation et ressources humaines", "التنظيم والموارد البشرية",
        ["ressources humaines", "organisation", "effectif", "personnel", "recrutement", "emplois"],
        ["human resources", "organisation", "staff", "headcount", "hiring", "employees"],
        ["الموارد البشرية", "التنظيم", "عدد الأعوان"],
        [crit("c_hc", "Gives headcount by year", "Donne l'effectif par année",
              ["effectif", "emplois", "recrutement", "salarié"], ["headcount", "employees", "hiring", "staff"], number=True),
         crit("c_pay", "States wage level", "Indique le niveau de salaire",
              ["salaire", "masse salariale", "rémunération"], ["salary", "wage", "payroll"], number=True)],
        ["headcount", "avg_gross_salary"]),
    sec("legal_structure", "Legal form and ownership", "Forme juridique et capital", "الشكل القانوني ورأس المال",
        ["forme juridique", "capital", "statut", "sarl", "suarl", "actionnaire", "associé"],
        ["legal form", "legal structure", "capital", "ownership", "shareholder", "sarl"],
        ["الشكل القانوني", "رأس المال", "الشركاء"],
        [crit("c_form", "States the legal form", "Indique la forme juridique",
              ["sarl", "suarl", "sa", "sas", "forme juridique"], ["sarl", "suarl", "sas", "legal form"]),
         crit("c_cap", "States share capital and split", "Indique le capital et la répartition",
              ["capital", "parts", "répartition"], ["capital", "shares", "split", "ownership"], number=True)],
        ["legal_form", "startup_label", "share_capital"]),
    sec("investment_plan", "Investment plan", "Plan d'investissement", "برنامج الاستثمار",
        ["investissement", "immobilisation", "équipement", "coût du projet"], ["investment", "capex", "fixed assets", "project cost"],
        ["الاستثمار", "التجهيزات"],
        [crit("c_items", "Itemises investments with amounts", "Détaille les investissements chiffrés",
              ["investissement", "immobilisation", "équipement", "dt"], ["investment", "capex", "equipment", "tnd"], number=True),
         crit("c_wc", "Includes working capital need", "Inclut le besoin en fonds de roulement",
              ["fonds de roulement", "bfr", "besoin en fonds"], ["working capital", "bfr"])],
        ["capex_items", "total_investment"]),
    sec("financing_plan", "Financing plan", "Plan de financement", "خطة التمويل",
        ["financement", "fonds propres", "emprunt", "crédit", "subvention", "apport"], ["financing", "funding", "equity", "loan", "grant", "own funds"],
        ["التمويل", "قرض", "أموال ذاتية", "منحة"],
        [crit("c_mix", "Splits equity, loan and grants", "Répartit fonds propres, crédit, subventions",
              ["fonds propres", "emprunt", "crédit", "subvention", "apport"], ["equity", "loan", "grant", "own funds"], number=True),
         crit("c_bal", "Sources equal uses", "Ressources égales emplois",
              ["emplois", "ressources", "total"], ["uses", "sources", "total"])],
        ["own_funds", "loan_amount", "loan_rate_pct", "loan_years", "grant_amount", "funding_instrument"]),
    sec("financial_projections", "Financial projections", "Prévisions financières", "التوقعات المالية",
        ["prévision", "compte de résultat", "trésorerie", "seuil de rentabilité", "chiffre d'affaires", "résultat"],
        ["projection", "forecast", "income statement", "cash flow", "break-even", "revenue", "profit"],
        ["توقعات", "نتيجة", "رقم المعاملات", "خزينة"],
        [crit("c_pl", "Has a multi-year income statement", "Contient un compte de résultat pluriannuel",
              ["chiffre d'affaires", "charges", "résultat"], ["revenue", "costs", "profit", "income"], number=True),
         crit("c_cf", "Has a cash-flow plan", "Contient un plan de trésorerie",
              ["trésorerie", "flux"], ["cash flow", "cash"], number=True),
         crit("c_be", "States break-even", "Indique le seuil de rentabilité",
              ["seuil de rentabilité", "point mort"], ["break-even", "breakeven"])],
        ["horizon_years", "revenue_by_year", "cogs_by_year", "opex_by_year", "payroll_by_year", "capex_by_year", "tax_rate_pct"]),
    sec("risks", "Risks and mitigation", "Risques et mesures d'atténuation", "المخاطر وسبل التخفيف",
        ["risque", "atténuation", "swot", "menace"], ["risk", "mitigation", "swot", "threat"],
        ["مخاطر", "تخفيف"],
        [crit("c_risk", "Names main risks", "Nomme les principaux risques",
              ["risque", "menace", "faiblesse"], ["risk", "threat", "weakness"]),
         crit("c_mit", "Gives a mitigation for each", "Donne une mesure pour chacun",
              ["atténu", "mesure", "plan b", "couvert"], ["mitigat", "measure", "contingency", "hedge"])],
        ["risks"], required=False, weight=0.6),
]

EXTENSION_EXTRA = [
    sec("existing_activity", "Existing activity and track record", "Activité existante et historique", "النشاط الحالي والتاريخ",
        ["activité existante", "historique", "bilan", "réalisations", "situation actuelle"],
        ["existing business", "track record", "historical", "current situation", "past performance"],
        ["النشاط الحالي", "الحصيلة"],
        [crit("c_hist", "Gives historical revenue and results", "Donne l'historique du CA et des résultats",
              ["chiffre d'affaires", "résultat", "historique", "exercice"], ["revenue", "result", "historical", "year"], number=True),
         crit("c_age", "States years in operation", "Indique l'ancienneté",
              ["création", "depuis", "ancienneté"], ["since", "founded", "years in operation"])],
        ["years_in_operation", "last_revenue", "last_net_income"]),
    sec("extension_project", "Extension project and expected impact", "Projet d'extension et impact attendu", "مشروع التوسعة والأثر",
        ["extension", "développement", "impact", "capacité", "emplois créés"],
        ["extension", "expansion", "impact", "capacity", "jobs created"],
        ["توسعة", "أثر", "طاقة"],
        [crit("c_cap", "States added capacity or output", "Indique la capacité supplémentaire",
              ["capacité", "production", "supplémentaire"], ["capacity", "output", "additional"], number=True),
         crit("c_jobs", "States jobs created", "Indique les emplois créés",
              ["emplois", "recrutement"], ["jobs", "hiring", "employment"], number=True)],
        ["extension_goal", "jobs_created"]),
]

GIZ_EXTRA = [
    sec("impact", "Impact (jobs, inclusion, sustainability)", "Impact (emploi, inclusion, durabilité)", "الأثر (التشغيل، الإدماج، الاستدامة)",
        ["impact", "emplois", "inclusion", "durabilité", "environnement", "social"],
        ["impact", "jobs", "inclusion", "sustainab", "environment", "social"],
        ["أثر", "تشغيل", "استدامة"],
        [crit("c_impact", "Describes social or environmental impact", "Décrit l'impact social ou environnemental",
              ["impact", "social", "environnement", "durable"], ["impact", "social", "environment", "sustainab"])],
        ["jobs_created", "impact_note"], required=False, weight=0.6),
]


PITCH = [
    sec("executive_summary", "Executive summary", "Résumé", "ملخص",
        ["executive summary", "summary", "résumé", "synthèse"], ["executive summary", "summary", "overview"], ["ملخص"],
        [crit("c_what", "States what the company does", "Dit ce que fait l'entreprise", ["activité", "produit"], ["we ", "our ", "company", "platform", "product", "service", "provide", "offer", "retrofit", "build"]),
         crit("c_traction", "Gives a headline figure", "Donne un chiffre clé", ["chiffre", "clients"], ["revenue", "customers", "users", "mrr", "arr", "pilot", "percent", "%", "clients", "projects", "buildings"], number=True)],
        ["project_name", "solution"]),
    sec("problem", "Problem", "Problème", "المشكل",
        ["problème", "besoin"], ["problem", "pain point"], ["مشكل"],
        [crit("c_problem", "Names a concrete customer problem", "Nomme un problème client concret", ["problème", "difficulté"], ["problem", "pain", "struggle", "gap", "wait", "face", "lack", "difficult", "challenge", "cost", "cannot", "slow", "expensive", "need"])],
        ["problem"]),
    sec("market", "Market", "Marché", "السوق",
        ["marché", "concurren"], ["market", "competitor", "competition"], ["السوق"],
        [crit("c_size", "Sizes the market", "Chiffre le marché", ["marché", "milliard"], ["market", "billion", "million", "tam", "sam"], number=True),
         crit("c_comp", "Names competitors", "Nomme les concurrents", ["concurrent"], ["competitor", "competitors", "alternative", "incumbent"])],
        ["market_size_note", "competitors"]),
    sec("business_model", "Business model", "Modèle économique", "نموذج العمل",
        ["modèle économique", "business model", "revenus"], ["business model", "revenue model", "pricing", "how we make money"], ["نموذج"],
        [crit("c_price", "Explains how money is made", "Explique comment l'entreprise gagne de l'argent", ["prix", "tarif", "abonnement"], ["price", "pricing", "subscription", "fee", "charge", "margin"], number=True)],
        ["revenue_streams", "pricing"]),
    sec("financials_ask", "Financials and funding ask", "Finances et besoin de financement", "الماليات وطلب التمويل",
        ["financ", "levée", "besoin"], ["financials", "funding ask", "funding", "use of funds", "ask"], ["تمويل"],
        [crit("c_fin", "Gives revenue, costs or burn", "Donne CA, charges ou burn", ["chiffre d'affaires", "charges"], ["revenue", "cost", "burn", "runway", "margin"], number=True),
         crit("c_ask", "States the ask and use of funds", "Indique le montant et l'usage", ["montant", "usage"], ["raise", "ask", "seeking", "use of funds"], number=True)],
        ["total_investment", "funding_sources"]),
    sec("team", "Team", "Équipe", "الفريق",
        ["équipe", "fondateur"], ["team", "founders", "management"], ["فريق"],
        [crit("c_team", "Names people and relevant experience", "Nomme les personnes et leur expérience", ["expérience", "ancien"], ["ceo", "cto", "cofounder", "former", "experience", "years"])],
        ["founders", "key_skills"]),
    sec("risks", "Risks", "Risques", "المخاطر",
        ["risque"], ["risks", "risk", "challenges"], ["مخاطر"],
        [crit("c_risk", "Names specific risks and mitigations", "Nomme les risques et leurs parades", ["risque", "parade"], ["risk", "mitigation", "mitigate", "plan b", "contingency"])],
        ["risks"], required=False, weight=0.8),
]


def template(tid, title, stage, sections, official_name):
    return {
        "id": tid,
        "title": title,
        "stage": stage,
        "version": "0.1.0",
        "verified_against_official_model": False,
        "official_model_file": official_name,
        "source_page": None,
        "note": "Derived skeleton. Not yet checked heading by heading against the official model.",
        "sections": sections,
    }


def main():
    OUT.mkdir(exist_ok=True)
    pack = {
        "bfpme_creation": template("bfpme_creation", "BFPME business plan (creation)", "creation", COMMON,
                                   "grants_and_financial_aids/Business_Plan_Models/Modele_Business_Plan_Creation.xls"),
        "bfpme_extension": template("bfpme_extension", "BFPME business plan (extension)", "extension",
                                    COMMON[:2] + EXTENSION_EXTRA + COMMON[2:], 
                                    "grants_and_financial_aids/Business_Plan_Models/Modele_Business_Plan_Extension.xls"),
        "giz": template("giz", "GIZ plan d'affaires", "any", COMMON[:-1] + GIZ_EXTRA + COMMON[-1:],
                        "grants_and_financial_aids/Business_Plan_Models/Modele_Plan_Affaires_GIZ.doc"),
        "investor_pitch": template("investor_pitch", "Investor pitch plan", "any", PITCH, "n/a (generic pitch structure)"),
    }
    for tid, data in pack.items():
        (OUT / f"{tid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("wrote", tid, len(data["sections"]), "sections")


if __name__ == "__main__":
    main()
