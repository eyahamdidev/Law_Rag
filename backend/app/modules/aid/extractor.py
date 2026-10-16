"""Extract structured founder profiles from natural language messages.

Uses LLM structured output via `aid.extract_profile@v2` with deterministic
fallback when offline. The LLM never decides program eligibility.
"""

import re
from typing import Any

from app.modules.aid.rules_engine import SECTOR_CLUSTERS, _normalize
from app.prompts.library import get_prompt
from app.schemas.aid import AidProfile
from app.services.llm import LLMUnavailable, get_llm

GOVERNORATES = [
    "ariana", "beja", "ben arous", "bizerte", "gabes", "gafsa", "jendouba",
    "kairouan", "kasserine", "kebili", "kef", "mahdia", "manouba", "medenine",
    "monastir", "nabeul", "sfax", "sidi bouzid", "siliana", "sousse",
    "tataouine", "tozeur", "tunis", "zaghouan",
    "القصرين", "سيدي بوزيد", "قفصة", "القيروان", "جندوبة", "الكاف", "سليانة",
    "باجة", "تطاوين", "قبلي", "مدنين", "قابس", "زغوان", "المهدية", "تونس",
]


def heuristic_extract_profile(text: str) -> AidProfile:
    """Deterministic heuristic extraction when LLM is offline."""
    norm = f" {_normalize(text)} "

    def has_word(word: str) -> bool:
        nw = _normalize(word)
        # For Arabic words, substring match in normalized text is safe
        if any("\u0600" <= c <= "\u06FF" for c in word):
            return nw in norm
        return bool(re.search(rf"\b{re.escape(nw)}\b", norm))

    # 1. Stage
    stage = "unspecified"
    if any(has_word(w) for w in ["creation", "creer", "cree", "lancer", "lance", "nouveau", "fonder", "ouvrir", "بعث", "تاسيس"]):
        stage = "creation"
    elif any(has_word(w) for w in ["extension", "etendre", "etend", "agrandir", "renouveler", "توسعة", "توسيع"]):
        stage = "extension"
    elif any(has_word(w) for w in ["croissance", "growth", "accelerer", "scale"]):
        stage = "growth"
    elif any(has_word(w) for w in ["idee", "idea", "concept", "فكرة"]):
        stage = "idea"

    # 2. Need
    need = "unspecified"
    if any(has_word(w) for w in ["subvention", "bourse", "don", "grant", "منحة"]):
        need = "grant"
    elif any(has_word(w) for w in ["credit", "pret", "emprunt", "loan", "قرض"]):
        need = "loan"
    elif any(has_word(w) for w in ["garantie", "caution", "guarantee", "ضمان"]):
        need = "guarantee"
    elif any(has_word(w) for w in ["impot", "fiscal", "exoneration", "degrevement", "tax", "جبائي", "اعفاء"]):
        need = "tax_incentive"
    elif any(has_word(w) for w in ["guide", "modele", "business plan", "accompagnement", "مخطط"]):
        need = "guidance"
    elif any(has_word(w) for w in ["financement", "financer", "finances", "funding", "تمويل"]):
        need = "financing"

    # 3. Sector
    sector = ""
    priority_clusters = ["greentech", "artisanat", "agroalimentaire", "industrie", "commerce_detail", "technologie", "services"]
    found = False
    for cluster_name in priority_clusters:
        synonyms = set(SECTOR_CLUSTERS.get(cluster_name, set()))
        if cluster_name == "technologie":
            synonyms.update(["logicielle", "startup"])
        for syn in sorted(synonyms, key=len, reverse=True):
            if has_word(syn):
                sector = cluster_name
                found = True
                break
        if found:
            break

    # 4. Investment amount
    funding_need_tnd = None
    amount_match = re.search(r"(\d+(?:[\s.,]\d+)?)\s*(?:الف|ألف|مليون)?\s*(?:dt|tnd|dinars?|دينار|الف|ألف|مليون)", text, re.IGNORECASE)
    if amount_match:
        raw_val = amount_match.group(1).replace(" ", "").replace(",", ".")
        try:
            val = float(raw_val)
            if "million" in text.lower() or "مليون" in text:
                val *= 1_000_000
            elif "ألف" in text or "الف" in text:
                val *= 1_000
            funding_need_tnd = val
        except ValueError:
            pass

    # 5. Governorate
    governorate = None
    for gov in GOVERNORATES:
        if has_word(gov):
            governorate = gov
            break

    # 6. Flags
    is_innovative = True if any(has_word(w) for w in ["innovant", "innovante", "ia", "tech", "iot", "greentech", "مبتكر"]) else None
    has_startup_label = True if any(has_word(w) for w in ["label startup", "labellisee", "علامة"]) else None
    is_graduate = True if any(has_word(w) for w in ["diplome", "ingenieur", "universitaire", "متخرج"]) else None

    return AidProfile(
        stage=stage,
        sector=sector,
        need=need,
        funding_need_tnd=funding_need_tnd,
        governorate=governorate,
        is_innovative=is_innovative,
        has_startup_label=has_startup_label,
        is_graduate=is_graduate,
        free_text=text,
    )


def extract_profile(
    question: str, known_profile: AidProfile | None = None
) -> tuple[AidProfile, list[str], str]:
    """Extract a validated AidProfile from text, returning (profile, missing_fields, prompt_version)."""
    llm = get_llm()
    prompt_spec = get_prompt("aid.extract_profile", "v2")
    version_ref = prompt_spec.ref

    if not llm.available:
        profile = heuristic_extract_profile(question)
        missing = []
        if profile.stage == "unspecified":
            missing.append("stage")
        if not profile.sector:
            missing.append("sector")
        if profile.need == "unspecified":
            missing.append("need")
        return profile, missing, "heuristic@v1"

    messages = prompt_spec.messages(
        question=question,
        profile=known_profile.model_dump_json() if known_profile else "{}",
    )

    try:
        data, _ = llm.chat_json(messages, tier="fast", max_tokens=300)
        stage = data.get("stage", "unspecified")
        if stage not in {"idea", "creation", "extension", "growth", "unspecified"}:
            stage = "unspecified"

        need = data.get("need", "unspecified")
        if need not in {"financing", "grant", "loan", "tax_incentive", "guarantee", "guidance", "unspecified"}:
            need = "unspecified"

        profile = AidProfile(
            stage=stage,
            sector=data.get("sector") or "",
            need=need,
            funding_need_tnd=data.get("funding_need_tnd"),
            governorate=data.get("governorate"),
            is_innovative=data.get("is_innovative"),
            has_startup_label=data.get("has_startup_label"),
            is_graduate=data.get("is_graduate"),
            free_text=question,
        )
        missing_fields = data.get("missing_fields") or []
        return profile, missing_fields, version_ref
    except (LLMUnavailable, Exception):
        profile = heuristic_extract_profile(question)
        missing = []
        if profile.stage == "unspecified":
            missing.append("stage")
        if not profile.sector:
            missing.append("sector")
        if profile.need == "unspecified":
            missing.append("need")
        return profile, missing, "heuristic@fallback"

