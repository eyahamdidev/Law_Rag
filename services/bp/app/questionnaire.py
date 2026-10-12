"""The business-plan questionnaire: question bank, parsing, validation, progress.

The bank is the module's own. The orchestrator may already know some answers
(stage, sector, legal form...). Those arrive in ``profile`` and are shown as
``prefilled`` so the founder confirms instead of retyping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.templates import label

STAGES = ["idea", "creation", "extension"]
LEGAL_FORMS = ["SUARL", "SARL", "SA", "SAS", "sole_proprietor", "other"]
EXPORT = ["none", "partial", "total"]
INSTRUMENTS = ["loan", "equity", "grant", "mixed", "none"]
STARTUP_LABEL = ["yes", "no", "pre_label"]
GOVERNORATES = [
    "Tunis", "Ariana", "Ben Arous", "Manouba", "Nabeul", "Zaghouan", "Bizerte", "Béja", "Jendouba", "Le Kef",
    "Siliana", "Sousse", "Monastir", "Mahdia", "Sfax", "Kairouan", "Kasserine", "Sidi Bouzid", "Gabès",
    "Médenine", "Tataouine", "Gafsa", "Tozeur", "Kébili",
]


@dataclass(frozen=True)
class Q:
    id: str
    group: str
    type: str  # text longtext choice number pct bool year_series items int
    required: bool
    en: str
    fr: str
    ar: str
    choices: tuple[str, ...] = ()
    profile: bool = False  # can be supplied by the orchestrator profile
    help_en: str = ""
    help_fr: str = ""


BANK: list[Q] = [
    # A. identity ----------------------------------------------------------------
    Q("project_name", "identity", "text", True, "Project or company name", "Nom du projet ou de l'entreprise", "اسم المشروع أو الشركة", profile=True),
    Q("stage", "identity", "choice", True, "Stage", "Stade du projet", "مرحلة المشروع", tuple(STAGES), True),
    Q("sector", "identity", "text", True, "Sector or activity", "Secteur ou activité", "القطاع أو النشاط", profile=True,
      help_en="Plain words are fine, for example 'SaaS for clinics' or 'olive oil packaging'.",
      help_fr="Des mots simples suffisent, par exemple « logiciel pour cliniques »."),
    Q("legal_form", "identity", "choice", True, "Legal form", "Forme juridique", "الشكل القانوني", tuple(LEGAL_FORMS), True),
    Q("startup_label", "identity", "choice", False, "Startup Act label", "Label Startup Act", "علامة Startup Act", tuple(STARTUP_LABEL), True),
    Q("governorate", "identity", "choice", False, "Governorate", "Gouvernorat", "الولاية", tuple(GOVERNORATES), True),
    Q("export_status", "identity", "choice", False, "Export status", "Statut d'exportation", "صفة التصدير", tuple(EXPORT), True),
    Q("share_capital", "identity", "number", False, "Share capital (TND)", "Capital social (TND)", "رأس المال (دينار)"),
    Q("years_in_operation", "identity", "int", False, "Years in operation (extension only)", "Ancienneté en années (extension)", "سنوات النشاط (للتوسعة)", profile=True),
    # B. offer & market ----------------------------------------------------------
    Q("problem", "offer", "longtext", True, "Which customer problem do you solve?", "Quel problème client résolvez-vous ?", "ما المشكل الذي تحلونه للحريف؟"),
    Q("solution", "offer", "longtext", True, "What is your product or service?", "Quel est votre produit ou service ?", "ما هو منتجكم أو خدمتكم؟"),
    Q("differentiator", "offer", "longtext", False, "What makes you different?", "Qu'est-ce qui vous différencie ?", "ما الذي يميزكم؟"),
    Q("target_customers", "market", "longtext", True, "Who are your target customers?", "Qui sont vos clients cibles ?", "من هم الحرفاء المستهدفون؟"),
    Q("market_size_note", "market", "longtext", False, "Market size and its source", "Taille du marché et sa source", "حجم السوق ومصدره",
      help_en="Give a figure only if you have a source. Otherwise leave it empty.",
      help_fr="Ne donnez un chiffre que si vous avez une source."),
    Q("competitors", "market", "longtext", False, "Main competitors or alternatives", "Principaux concurrents ou alternatives", "أهم المنافسين أو البدائل"),
    Q("pricing", "market", "longtext", True, "Pricing (price per unit or plan)", "Prix (par unité ou formule)", "الأسعار"),
    Q("channels", "market", "longtext", False, "Sales and distribution channels", "Canaux de vente et distribution", "قنوات البيع والتوزيع"),
    # C. team & operations -------------------------------------------------------
    Q("founders", "team", "longtext", False, "Founders and their roles", "Promoteurs et leurs rôles", "الباعثون وأدوارهم"),
    Q("key_skills", "team", "longtext", False, "Experience and key skills", "Expérience et compétences clés", "الخبرة والمهارات"),
    Q("headcount", "team", "int", True, "Planned headcount at start", "Effectif prévu au démarrage", "عدد الأعوان عند الانطلاق", profile=True),
    Q("avg_gross_salary", "team", "number", False, "Average gross monthly salary (TND)", "Salaire brut mensuel moyen (TND)", "متوسط الأجر الخام الشهري (دينار)", profile=True),
    Q("production_means", "operations", "longtext", False, "Equipment and premises", "Équipements et locaux", "التجهيزات والمحلات"),
    Q("suppliers", "operations", "longtext", False, "Main suppliers", "Principaux fournisseurs", "أهم المزودين"),
    Q("imported_share_pct", "operations", "pct", False, "Share of costs in foreign currency or imported (%)", "Part des coûts en devises ou importée (%)", "نسبة الكلفة بالعملة الأجنبية (%)"),
    # D. investment & financing --------------------------------------------------
    Q("capex_items", "investment", "items", False, "Investments, one per line as 'label: amount'", "Investissements, un par ligne « libellé : montant »", "الاستثمارات: «البيان: المبلغ»"),
    Q("total_investment", "investment", "number", True, "Total investment incl. working capital (TND)", "Investissement total y compris BFR (TND)", "الاستثمار الجملي (دينار)"),
    Q("funding_instrument", "financing", "choice", True, "Main funding instrument", "Instrument de financement principal", "أداة التمويل الرئيسية", tuple(INSTRUMENTS), True),
    Q("funding_need_amount", "financing", "number", False, "External funding needed (TND)", "Financement externe recherché (TND)", "التمويل الخارجي المطلوب (دينار)", profile=True),
    Q("own_funds", "financing", "number", False, "Own funds contributed (TND)", "Apport en fonds propres (TND)", "الأموال الذاتية (دينار)"),
    Q("loan_amount", "financing", "number", False, "Bank loan (TND)", "Crédit bancaire (TND)", "القرض البنكي (دينار)"),
    Q("loan_rate_pct", "financing", "pct", False, "Loan interest rate (%)", "Taux d'intérêt du crédit (%)", "نسبة فائدة القرض (%)"),
    Q("loan_years", "financing", "int", False, "Loan duration (years)", "Durée du crédit (années)", "مدة القرض (سنوات)"),
    Q("grace_years", "financing", "int", False, "Grace period (years)", "Différé (années)", "فترة الإمهال (سنوات)"),
    Q("grant_amount", "financing", "number", False, "Grants or subsidies (TND)", "Subventions (TND)", "المنح (دينار)"),
    # E. projections -------------------------------------------------------------
    Q("horizon_years", "projections", "choice", True, "Projection horizon (years)", "Horizon de projection (années)", "أفق التوقعات (سنوات)", ("3", "5")),
    Q("revenue_by_year", "projections", "year_series", True, "Revenue per year (TND)", "Chiffre d'affaires par année (TND)", "رقم المعاملات سنويا (دينار)",
      help_en="One number per year, separated by commas.", help_fr="Un chiffre par année, séparés par des virgules."),
    Q("cogs_by_year", "projections", "year_series", False, "Direct costs per year: purchases, materials (TND)", "Coûts directs par année : achats, matières (TND)", "الكلفة المباشرة سنويا (دينار)"),
    Q("payroll_by_year", "projections", "year_series", False, "Payroll per year incl. social charges (TND)", "Masse salariale par année charges comprises (TND)", "كتلة الأجور سنويا (دينار)"),
    Q("opex_by_year", "projections", "year_series", False, "Other operating costs per year (TND)", "Autres charges d'exploitation par année (TND)", "مصاريف الاستغلال الأخرى (دينار)"),
    Q("capex_by_year", "projections", "year_series", False, "Investment spending per year (TND)", "Dépenses d'investissement par année (TND)", "نفقات الاستثمار سنويا (دينار)"),
    Q("tax_rate_pct", "projections", "pct", False, "Corporate tax rate used (%)", "Taux d'IS utilisé (%)", "نسبة الضريبة على الشركات (%)",
      help_en="Leave empty to use the module default and confirm it with your accountant.",
      help_fr="Laissez vide pour le taux par défaut, à confirmer avec votre comptable."),
    # F. extension / impact ------------------------------------------------------
    Q("last_revenue", "extension", "number", False, "Last year's revenue (extension, TND)", "CA du dernier exercice (extension, TND)", "رقم معاملات آخر سنة (دينار)"),
    Q("last_net_income", "extension", "number", False, "Last year's net result (extension, TND)", "Résultat net du dernier exercice (TND)", "النتيجة الصافية لآخر سنة (دينار)"),
    Q("extension_goal", "extension", "longtext", False, "What does the extension add?", "Qu'apporte l'extension ?", "ما الذي ستضيفه التوسعة؟"),
    Q("jobs_created", "extension", "int", False, "Jobs created", "Emplois créés", "مواطن الشغل المحدثة"),
    Q("impact_note", "extension", "longtext", False, "Social or environmental impact", "Impact social ou environnemental", "الأثر الاجتماعي أو البيئي"),
    Q("risks", "risks", "longtext", False, "Main risks and how you handle them", "Principaux risques et mesures", "أهم المخاطر وسبل معالجتها"),
]

BANK_BY_ID: dict[str, Q] = {q.id: q for q in BANK}
PROFILE_IDS = [q.id for q in BANK if q.profile]
REQUIRED_IDS = [q.id for q in BANK if q.required]
SERIES_IDS = [q.id for q in BANK if q.type == "year_series"]

# Orchestrator profile keys -> question ids. The orchestrator (aid tab, chat) uses its own names.
PROFILE_ALIASES = {
    "company_name": "project_name", "project": "project_name", "name": "project_name",
    "stage": "stage",
    "sector": "sector", "activity": "sector",
    "legal_form": "legal_form", "form": "legal_form",
    "startup_label": "startup_label", "startup": "startup_label",
    "governorate": "governorate", "region": "governorate", "location": "governorate",
    "export_status": "export_status", "export": "export_status",
    "headcount": "headcount", "employees": "headcount", "team_size": "headcount",
    "avg_gross_salary": "avg_gross_salary", "avg_salary": "avg_gross_salary", "salary": "avg_gross_salary",
    "funding_amount": "funding_need_amount", "amount": "funding_need_amount", "funding_need_amount": "funding_need_amount",
    "funding_instrument": "funding_instrument", "years_in_operation": "years_in_operation",
}
STAGE_ALIASES = {"idea": "idea", "creation": "creation", "création": "creation", "extension": "extension", "growth": "extension"}
NEED_TO_INSTRUMENT = {"financing": "loan", "loan": "loan", "grant": "grant", "equity": "equity", "mixed": "mixed"}


class ParseError(ValueError):
    pass


_NUM = re.compile(r"[-+]?\d[\d\s  .,]*")


def parse_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ParseError("not a number")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace("tnd", "").replace("dt", "").replace("dinars", "").strip()
    mult = 1.0
    if text.endswith("k"):
        mult, text = 1e3, text[:-1]
    elif text.endswith("m") and re.search(r"\d", text[:-1] or "x"):
        mult, text = 1e6, text[:-1]
    m = _NUM.fullmatch(text.strip())
    if not m:
        raise ParseError(f"'{value}' is not a number")
    s = re.sub(r"[\s  ]", "", m.group(0))
    if "," in s and "." in s:
        # the last separator is the decimal one
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + "." + tail if len(tail) != 3 else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if len(tail) == 3 and head.isdigit() and len(head) <= 3 and tail.isdigit() and mult == 1.0:
            s = head + tail  # '50.000' reads as fifty thousand in a Tunisian plan
    try:
        return float(s) * mult
    except ValueError as exc:
        raise ParseError(f"'{value}' is not a number") from exc


def parse_series(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        return [parse_number(v) for v in value]
    text = str(value).strip()
    parts = [p for p in re.split(r"[;\n|]+", text) if p.strip()]
    if len(parts) <= 1:
        parts = [p for p in re.split(r",\s+", text) if p.strip()]
    if len(parts) <= 1 and "," in text and not re.fullmatch(r"\d{1,3}(,\d{3})+", text) and not re.fullmatch(r"\d+,\d{1,2}", text):
        parts = [p for p in text.split(",") if p.strip()]
    if len(parts) <= 1:
        parts = [text]
    return [parse_number(p) for p in parts]


def parse_items(value: Any) -> list[dict]:
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append({"label": str(item.get("label", "")).strip(), "amount": parse_number(item.get("amount"))})
            else:
                raise ParseError("each item needs a label and an amount")
        return out
    out = []
    for line in re.split(r"[\n;]+", str(value)):
        if not line.strip():
            continue
        lab, sep, amt = line.rpartition(":")
        if not sep:
            raise ParseError(f"'{line.strip()}' needs the form 'label: amount'")
        out.append({"label": lab.strip(), "amount": parse_number(amt)})
    return out


def normalise(q: Q, value: Any) -> Any:
    """Return the cleaned value or raise ParseError. Empty input returns None."""
    if value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and not value):
        return None
    t = q.type
    if t in ("text", "longtext"):
        return str(value).strip()
    if t == "choice":
        s = str(value).strip()
        for c in q.choices:
            if s.lower() == c.lower():
                return c
        if q.id == "stage" and s.lower() in STAGE_ALIASES:
            return STAGE_ALIASES[s.lower()]
        if q.id == "startup_label":
            if s.lower() in ("true", "oui", "yes", "1"):
                return "yes"
            if s.lower() in ("false", "non", "no", "0"):
                return "no"
        if q.id == "funding_instrument" and s.lower() in NEED_TO_INSTRUMENT:
            return NEED_TO_INSTRUMENT[s.lower()]
        if q.id == "governorate":  # free spelling is common: accept and keep trimmed
            return s
        raise ParseError(f"'{s}' is not one of: {', '.join(q.choices)}")
    if t == "bool":
        return str(value).strip().lower() in ("1", "true", "yes", "oui", "نعم")
    if t in ("number", "pct", "int"):
        n = parse_number(value)
        if t == "pct" and not (0 <= n <= 100):
            raise ParseError("a percentage must be between 0 and 100")
        if n < 0:
            raise ParseError("must not be negative")
        return int(round(n)) if t == "int" else n
    if t == "year_series":
        s = parse_series(value)
        if any(v < 0 for v in s):
            raise ParseError("must not contain negative numbers")
        return s
    if t == "items":
        return parse_items(value)
    raise ParseError(f"unsupported type {t}")


@dataclass
class Cleaned:
    values: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)


def clean_answers(raw: dict[str, Any] | None) -> Cleaned:
    out = Cleaned()
    for key, val in (raw or {}).items():
        q = BANK_BY_ID.get(key)
        if q is None:
            out.unknown.append(key)
            continue
        try:
            v = normalise(q, val)
        except ParseError as exc:
            out.errors[key] = str(exc)
            continue
        if v is not None:
            out.values[key] = v
    horizon = out.values.get("horizon_years")
    if horizon is not None:
        out.values["horizon_years"] = int(horizon)
    return out


def clean_profile(raw: dict[str, Any] | None) -> Cleaned:
    """Map orchestrator keys onto question ids, then normalise like answers."""
    mapped: dict[str, Any] = {}
    for key, val in (raw or {}).items():
        qid = PROFILE_ALIASES.get(key)
        if key == "need" and val in NEED_TO_INSTRUMENT:
            qid, val = "funding_instrument", NEED_TO_INSTRUMENT[val]
        if qid is None:
            continue
        if val in (None, "", "unspecified"):
            continue
        mapped.setdefault(qid, val)
    cleaned = clean_answers(mapped)
    return cleaned


def describe(lang: str) -> list[dict]:
    """Static question definitions for the UI, in the requested language."""
    out = []
    for q in BANK:
        lab = {"en": q.en, "fr": q.fr, "ar": q.ar}
        hlp = {"en": q.help_en, "fr": q.help_fr}
        out.append({
            "id": q.id, "group": q.group, "type": q.type, "required": q.required,
            "choices": list(q.choices), "label": label(lab, lang), "help": hlp.get(lang) or hlp["en"],
            "orchestrator_can_prefill": q.profile,
        })
    return out
