"""Keyword baseline for routing.

Used when no LLM is reachable or the planner returns unusable JSON, and as
the baseline the LLM planner is compared against in eval/routing_eval.py.
It maps the message to agent ids by term lists. It cannot write sub-tasks or
translate the search query, so every chosen agent gets the raw message.
"""

AGENT_TERMS: dict[str, tuple[str, ...]] = {
    "fraud": (
        "fraud", "fraude", "frauduleux", "arnaque", "escroquerie", "fausse facture",
        "facture fictive", "suspect", "suspicious", "scam", "clause abusive",
        "unfair term", "safe to sign", "احتيال", "تحيل",
    ),
    "grants": (
        "aide", "subvention", "grant", "financement", "financer", "funding", "fund ",
        "prêt", "pret ", "loan", "crédit", "credit", "bfpme", "bts", "fonapram",
        "sotugar", "garantie", "prime", "incitation", "investisseur", "accélérateur",
        "accelerator", "incubateur", "seed", "levée de fonds", "تمويل", "منحة", "قرض",
    ),
    "business_plan": (
        "business plan", "plan d'affaires", "bmc", "business model", "canvas",
        "lean canvas", "prévisionnel", "previsionnel", "projection", "rentabilité",
        "seuil de rentabilité", "break-even", "cash flow", "comptab", "bilan",
        "مخطط أعمال", "نموذج العمل",
    ),
    "marketing": (
        "marketing", "clientèle", "clients", "customers", "prix de vente", "pricing",
        "positionnement", "positioning", "publicité", "réseaux sociaux", "social media",
        "go-to-market", "concurrent", "competitor", "تسويق", "حرفاء",
    ),
    "legal": (
        "patent", "brevet", "trademark", "copyright", "intellectual property", "propriété intellectuelle",
        "contract", "contrat", "agreement", "nda", "pacte", "founder", "shareholder", "licence",
        "براءة", "اختراع", "حق المؤلف", "عقد", "اتفاقية", "ملكية فكرية",
        "loi", "law", "legal", "juridique", "article", "décret", "decret", "code",
        "sarl", "suarl", "société", "societe", "company", "statuts", "capital",
        "associé", "registre", "label", "startup act", "bct", "devise", "change",
        "foreign currency", "crowdfunding", "faillite", "insolvency", "tva", "impôt",
        "impot", "tax", "قانون", "الفصل", "شركة", "علامة", "المؤسسة الناشئة",
    ),
}


def keyword_route(question: str) -> list[str]:
    text = f" {question.lower()} "
    return [agent for agent, terms in AGENT_TERMS.items() if any(term in text for term in terms)]
