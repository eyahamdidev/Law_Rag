"""Keyword baseline for intent and domain.

The deck's routing target is Macro-F1 >= 0.90 on about 60 labelled queries,
measured after this baseline. Replace this function without changing the
ChatResponse contract.
"""

from dataclasses import dataclass

FRAUD_TERMS = (
    "fraud",
    "fraude",
    "frauduleux",
    "arnaque",
    "fausse facture",
    "facture fictive",
    "suspicious",
    "suspect",
    "anomalie",
    "anomaly",
    "duplicate invoice",
    "double facture",
)

AID_TERMS = (
    "aide",
    "aides",
    "grant",
    "subvention",
    "bfpme",
    "financement",
    "financer",
    "prime",
    "incitation",
    "business plan",
    "prêt",
    "pret",
    "crédit",
    "credit",
    "startup act",
)

LEGAL_STYLE_TERMS = (
    "article",
    "loi",
    "code",
    "décret",
    "decret",
    "circulaire",
    "jort",
)

DOMAIN_TERMS = {
    "tax": ("impôt", "impot", "tva", "taxe", "fiscal", "dgi", "irpp", "is "),
    "banking": (
        "banque",
        "bancaire",
        "bct",
        "change",
        "devise",
        "compte",
        "circulaire",
    ),
    "labour": (
        "travail",
        "salarié",
        "salarie",
        "cnss",
        "licenciement",
        "employé",
        "employe",
    ),
    "intellectual_property": (
        "propriété intellectuelle",
        "propriete intellectuelle",
        "marque",
        "brevet",
        "droit d'auteur",
        "inpi",
    ),
    "legal": (
        "société",
        "societe",
        "sarl",
        "suarl",
        "création",
        "creation",
        "associé",
        "associe",
        "capital",
        "registre",
        "statuts",
    ),
}


@dataclass(frozen=True)
class RouteDecision:
    intent: str
    domains: list[str]
    needs_clarification: bool
    detail: str


def _contains(text: str, term: str) -> bool:
    return term in text


def route_query(question: str) -> RouteDecision:
    text = question.lower()

    if any(_contains(text, term) for term in FRAUD_TERMS):
        return RouteDecision(
            intent="fraud",
            domains=[],
            needs_clarification=False,
            detail="Keyword baseline sent this to fraud review.",
        )

    aid_hit = any(_contains(text, term) for term in AID_TERMS)
    legal_style = any(_contains(text, term) for term in LEGAL_STYLE_TERMS)
    if aid_hit and not legal_style:
        return RouteDecision(
            intent="aid",
            domains=[],
            needs_clarification=False,
            detail="Keyword baseline sent this to aid and financing.",
        )

    domains = [
        name
        for name, terms in DOMAIN_TERMS.items()
        if any(_contains(text, term) for term in terms)
    ]
    if not domains:
        return RouteDecision(
            intent="rag",
            domains=[],
            needs_clarification=True,
            detail=(
                "No domain keyword matched. Ask whether this is company law, "
                "tax, banking, labour, or intellectual property."
            ),
        )

    return RouteDecision(
        intent="rag",
        domains=domains,
        needs_clarification=False,
        detail="Keyword baseline selected " + ", ".join(domains) + ".",
    )
