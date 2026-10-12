"""Reference knowledge from the dataset pack: sector benchmarks, curated parameters, cited passages.

Three parts, all optional. The module works without them and says so.

* ``data/benchmarks.sqlite``  Damodaran tables (US data: margins, cost of capital, country risk).
* ``data/parameters.json``    A few Tunisian parameters with source, date and a ``verified`` flag.
* ``data/knowledge.sqlite``   Passages from the pack (tax code, accounting standards, guides) in a
                              full-text index, built by ``scripts/build_knowledge.py``.

Rule: every figure that comes from here carries its source and region. US sector margins are
never presented as a Tunisian norm.
"""

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache

from app.agents.common import fold
from app.config import SERVICE_ROOT

DATA = SERVICE_ROOT / "data"

# free-text sector words (EN, FR, AR) -> Damodaran industry name. First match wins, so specific rows come first.
SECTOR_MAP: list[tuple[tuple[str, ...], str]] = [
    (("saas", "software", "booking app", "mobile app", "web app", "booking platform", "logiciel", "application", "app mobile", "plateforme", "platform", "برمجيات"), "Software (System & Application)"),
    (("internet", "e-commerce", "ecommerce", "marketplace", "commerce en ligne"), "Software (Internet)"),
    (("jeu video", "video game", "gaming studio"), "Software (Entertainment)"),
    (("informatique", "it service", "esn", "consulting it", "conseil informatique", "cybersecurit"), "Computer Services"),
    (("restaurant", "cafe", "café", "snack", "restauration", "مطعم"), "Restaurant/Dining"),
    (("hotel", "hôtel", "guest house", "maison d'hote", "hebergement", "tourisme", "فندق"), "Hotel/Gaming"),
    (("agricol", "agricult", "farming", "ferme", "olive", "huile d'olive", "فلاحة"), "Farming/Agriculture"),
    (("agroalimentaire", "food processing", "transformation alimentaire", "conserve", "boulangerie", "patisserie", "pâtisserie", "biscuit"), "Food Processing"),
    (("boisson", "beverage", "jus", "eau minerale", "soft drink"), "Beverage (Soft)"),
    (("textile", "habillement", "vetement", "vêtement", "apparel", "confection", "clothing", "ملابس"), "Apparel"),
    (("chaussure", "shoe", "footwear"), "Shoe"),
    (("meuble", "furniture", "menuiserie", "bois", "decoration", "décoration"), "Furn/Home Furnishings"),
    (("pharmac", "medicament", "médicament"), "Drugs (Pharmaceutical)"),
    (("clinique", "clinic", "hospital", "hôpital", "sante", "santé", "healthcare facilit"), "Hospitals/Healthcare Facilities"),
    (("dispositif medical", "medical device", "healthcare product", "materiel medical"), "Healthcare Products"),
    (("education", "éducation", "formation", "ecole", "école", "training", "e-learning", "تعليم"), "Education"),
    (("solaire", "photovolta", "renewable", "renouvelable", "eolien", "éolien", "energie verte"), "Green & Renewable Energy"),
    (("recyclage", "dechet", "déchet", "waste", "environnement"), "Environmental & Waste Services"),
    (("transport", "logistique", "logistics", "livraison", "delivery"), "Transportation"),
    (("immobilier", "real estate", "promotion immobiliere"), "Real Estate (Development)"),
    (("btp", "construction", "batiment", "bâtiment", "genie civil"), "Engineering/Construction"),
    (("materiaux de construction", "building material", "ciment", "carrelage"), "Building Materials"),
    (("emballage", "packaging"), "Packaging & Container"),
    (("plastique", "caoutchouc", "rubber"), "Rubber& Tires"),
    (("electronique", "électronique", "electronics", "iot", "capteur"), "Electronics (General)"),
    (("machine", "equipement industriel", "machinery", "mecanique", "mécanique"), "Machinery"),
    (("publicite", "publicité", "advertising", "marketing agency", "agence de communication"), "Advertising"),
    (("telecom", "télécom"), "Telecom. Services"),
    (("assurance", "insurance"), "Insurance (General)"),
    (("fintech", "paiement", "microfinance", "credit", "crédit"), "Financial Svcs. (Non-bank & Insurance)"),
    (("grossiste", "wholesale", "distribution alimentaire"), "Food Wholesalers"),
    (("epicerie", "épicerie", "supermarche", "supermarché", "grocery"), "Retail (Grocery and Food)"),
    (("boutique", "retail", "commerce de detail", "vente au detail", "magasin"), "Retail (General)"),
    (("conseil", "consulting", "services aux entreprises", "business service", "freelance", "agence"), "Business & Consumer Services"),
    (("loisir", "sport", "fitness", "recreation", "salle de sport"), "Recreation"),
    (("media", "média", "presse", "edition", "édition", "publishing"), "Publishing & Newspapers"),
    (("cosmetique", "cosmétique", "hygiene", "hygiène", "household"), "Household Products"),
]


@lru_cache(maxsize=1)
def parameters() -> dict:
    p = DATA / "parameters.json"
    if not p.exists():
        return {}
    return {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def param(key: str) -> dict | None:
    return parameters().get(key)


def _db(name: str) -> sqlite3.Connection | None:
    path = DATA / name
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


@lru_cache(maxsize=1)
def _bench() -> sqlite3.Connection | None:
    return _db("benchmarks.sqlite")


@lru_cache(maxsize=1)
def _kb() -> sqlite3.Connection | None:
    return _db("knowledge.sqlite")


def benchmarks_available() -> bool:
    return _bench() is not None


def passages_available() -> bool:
    return _kb() is not None


def industry_for(sector: str | None) -> str | None:
    if not sector:
        return None
    f = fold(sector)
    for words, industry in SECTOR_MAP:
        if any(fold(w) in f for w in words):
            return industry
    return None


def industry_benchmark(industry: str) -> dict | None:
    con = _bench()
    if con is None:
        return None
    m = con.execute("select * from margins where industry=?", (industry,)).fetchone()
    w = con.execute("select * from wacc where industry=?", (industry,)).fetchone()
    if m is None:
        return None
    return {
        "industry": industry, "region": m["region"], "as_of": m["as_of"], "firms": m["firms"], "source_id": m["source_id"],
        "after_tax_operating_margin": m["at_op_margin"], "return_on_capital": m["roc"],
        "cost_of_capital": w["cost_of_capital"] if w else None, "cost_of_capital_region": w["region"] if w else None,
    }


def tunisia_country_risk() -> dict | None:
    con = _bench()
    if con is None:
        return None
    r = con.execute("select * from country_risk where country='Tunisia'").fetchone()
    return None if r is None else {"rating": r["rating"], "country_risk_premium": r["country_risk_premium"], "total_erp": r["total_erp"],
                                  "source_id": r["source_id"], "label": "Damodaran country risk, mid-2026 file"}


def _fts_query(text: str) -> str:
    toks = [t for t in re.findall(r"\w{3,}", fold(text)) if t not in STOP]
    return " OR ".join(f'"{t}"' for t in list(dict.fromkeys(toks))[:12])


STOP = {"the", "and", "des", "les", "une", "pour", "dans", "que", "sur", "avec", "par", "est", "section", "plan"}


def search(query: str, k: int = 2, source_ids: tuple[str, ...] | None = None) -> list[dict]:
    """Best passages from the pack by BM25. Each hit names its source, so the report can cite it."""
    con = _kb()
    q = _fts_query(query)
    if con is None or not q:
        return []
    try:
        rows = con.execute(
            "select p.id, p.source_id, p.locator, p.text, s.title, s.url, s.language, bm25(passages_fts) as rank "
            "from passages_fts join passages p on p.id = passages_fts.rowid join sources s on s.source_id = p.source_id "
            "where passages_fts match ? order by rank limit ?", (q, k * 6)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for r in rows:
        if source_ids and r["source_id"] not in source_ids:
            continue
        out.append({"id": f"{r['source_id']}#{r['id']}", "doc_id": r["source_id"], "title": f"{r['title']} ({r['locator']})",
                    "text": r["text"][:700], "score": round(-r["rank"], 3), "score_kind": "relevance", "url": r["url"], "origin": "pack"})
        if len(out) >= k:
            break
    return out
