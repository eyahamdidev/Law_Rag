
"""Deterministic rule engine for Tunisian funding and aid programs.

Rule evaluation sequence:
  Stage -> Sector -> Size / Capital -> Need -> Specific Conditions

The LLM never decides eligibility. All eligibility traces are deterministic
and grounded in source documents.
"""

import re
import unicodedata
from typing import Any

from app.modules.aid.catalog import CATALOG
from app.schemas.aid import (
    AidProfile,
    AidProgram,
    DocumentChecklist,
    Handoff,
    RuleTraceEntry,
)

SECTOR_CLUSTERS: dict[str, set[str]] = {
    "technologie": {
        "technologie", "technology", "tech", "tic", "it", "software",
        "logiciel", "digital", "deeptech", "fintech", "edtech",
        "healthtech", "iot", "برمجيات", "تكنولوجيا", "رقمي"
    },
    "industrie": {
        "industrie", "industry", "industriel", "mecanique", "textile",
        "composants_electroniques", "energies_renouvelables",
        "renewable_energy", "recyclage", "agroalimentaire", "confection",
        "صناعة", "صناعي"
    },
    "agroalimentaire": {
        "agroalimentaire", "agri", "agritech", "agriculture", "alimentation", "huilerie",
        "غذائية", "غذائي", "فلاحي", "فلاحة"
    },
    "services": {
        "services", "service", "logistique", "logistics", "maintenance",
        "conseil", "consulting", "خدمات"
    },
    "greentech": {
        "greentech", "cleantech", "environnement", "environment",
        "recyclage", "recycling", "energies_renouvelables", "renewable_energy"
    },
    "artisanat": {
        "artisanat", "craft", "artisan", "metiers", "menuiserie", "حرفي", "تقليدي"
    },
    "commerce_detail": {
        "commerce_detail", "commerce_pur", "retail", "magasin", "salon_de_the",
        "restaurant", "commerce_traditionnel", "commerce", "تجارة"
    },
}

LAW_HANDOFF_PATTERNS = [
    re.compile(r"\b(article|art\.?)\s+\d+", re.IGNORECASE),
    re.compile(r"\b(loi|decret|code|circulaire)\s+(n[°o]?\s*)?\d+", re.IGNORECASE),
    re.compile(r"\bque\s+dit\s+la\s+loi\b", re.IGNORECASE),
    re.compile(r"\bque\s+prevoit\s+le\s+code\b", re.IGNORECASE),
    re.compile(r"\b(الفصل|المادة|قانون|مجلة|منشور)\b", re.IGNORECASE),
]


def _normalize(text: str | None) -> str:
    """Normalize text by folding case, accents, and punctuation while preserving Arabic."""
    if not text:
        return ""
    # Standardize Arabic letter variants (alif, teh marbuta, ya/hamza)
    text = (
        text.replace("ة", "ه")
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ئ", "ي")
        .replace("ى", "ي")
    )
    normalized = unicodedata.normalize("NFKD", text)
    cleaned = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", cleaned.lower()).strip()


def detect_law_handoff(text: str | None) -> Handoff | None:
    """Detect if the query asks about statute content and should be handed off to P1 (Law)."""
    if not text:
        return None
    for pattern in LAW_HANDOFF_PATTERNS:
        if pattern.search(text):
            return Handoff(to="law", question=text)
    return None


def _matches_sector(program: AidProgram, profile_sector: str) -> tuple[bool, str]:
    """Check if profile sector matches program sectors and is not excluded."""
    if not profile_sector:
        return True, "Sector unspecified, kept open"

    norm_sec = _normalize(profile_sector)

    # 1. Check exclusions
    for exc in program.excluded_sectors:
        norm_exc = _normalize(exc)
        if norm_exc in norm_sec or norm_sec in norm_exc:
            return False, f"Sector '{profile_sector}' is explicitly excluded ({program.excluded_sectors})"
        if norm_exc in SECTOR_CLUSTERS and any(s in norm_sec for s in SECTOR_CLUSTERS[norm_exc]):
            return False, f"Sector '{profile_sector}' is in excluded cluster '{norm_exc}'"

    # 2. Check inclusions
    if not program.sectors:
        return True, "Program open to all non-excluded sectors"

    for inc in program.sectors:
        norm_inc = _normalize(inc)
        if norm_inc in norm_sec or norm_sec in norm_inc:
            return True, f"Sector '{profile_sector}' directly matches '{inc}'"
        if norm_inc in SECTOR_CLUSTERS and any(s in norm_sec for s in SECTOR_CLUSTERS[norm_inc]):
            return True, f"Sector '{profile_sector}' matches cluster '{norm_inc}'"
        for cluster_name, synonyms in SECTOR_CLUSTERS.items():
            if norm_inc in synonyms and any(s in norm_sec for s in synonyms):
                return True, f"Sector '{profile_sector}' matches cluster '{cluster_name}'"

    return False, f"Sector '{profile_sector}' not in eligible sectors ({program.sectors})"


def _matches_need(program: AidProgram, profile_need: str) -> bool:
    """Check if the program instrument type fits the founder's requested need."""
    if not profile_need or profile_need == "unspecified":
        return True

    pid = program.id
    pt = program.program_type

    if pid == "giz-business-plan":
        return profile_need in {"guidance", "financing", "unspecified"}

    if profile_need == "financing":
        # Startup Act provides cash stipend / bourse de startup
        if pid == "startup-act":
            return True
        return pt in {"loan", "grant", "guarantee", "mixed"}

    if profile_need == "grant":
        return pt in {"grant", "mixed"}

    if profile_need == "loan":
        return pt in {"loan", "guarantee", "mixed"}

    if profile_need == "tax_incentive":
        return pt in {"tax_incentive", "mixed"} or pid in {"startup-act", "investment-incentives"}

    if profile_need == "guarantee":
        return pt in {"guarantee", "mixed"}

    if profile_need == "guidance":
        return pid in {"giz-business-plan", "startup-act", "investment-incentives"} or pt == "mixed"

    return pt == profile_need


def evaluate_program(
    program: AidProgram, profile: AidProfile
) -> tuple[bool, list[str], list[RuleTraceEntry]]:
    """Deterministically evaluate eligibility for a single program."""
    traces: list[RuleTraceEntry] = []
    reasons: list[str] = []

    # 1. Stage Check
    if profile.stage and profile.stage != "unspecified":
        stage_passed = profile.stage in program.stages
        traces.append(
            RuleTraceEntry(
                program_id=program.id,
                step="stage",
                passed=stage_passed,
                criterion="stage_matching",
                details=(
                    f"Profile stage '{profile.stage}' in {program.stages}"
                    if stage_passed
                    else f"Profile stage '{profile.stage}' not in {program.stages}"
                ),
            )
        )
        if not stage_passed:
            reasons.append(f"Incompatible stage: requires {program.stages}")
    else:
        traces.append(
            RuleTraceEntry(
                program_id=program.id,
                step="stage",
                passed=True,
                criterion="stage_matching",
                details="Stage unspecified, skipping stage filter",
            )
        )

    # 2. Sector Check
    sector_passed, sector_details = _matches_sector(program, profile.sector)
    traces.append(
        RuleTraceEntry(
            program_id=program.id,
            step="sector",
            passed=sector_passed,
            criterion="sector_constraints",
            details=sector_details,
        )
    )
    if not sector_passed:
        reasons.append(sector_details)

    # 3. Size / Investment Check
    size_passed = True
    size_details = []
    if profile.employees is not None:
        if program.max_employees and profile.employees > program.max_employees:
            size_passed = False
            size_details.append(
                f"Headcount {profile.employees} exceeds max {program.max_employees}"
            )
        if program.min_employees and profile.employees < program.min_employees:
            size_passed = False
            size_details.append(
                f"Headcount {profile.employees} below min {program.min_employees}"
            )

    if profile.funding_need_tnd is not None:
        if program.max_investment_tnd and profile.funding_need_tnd > program.max_investment_tnd:
            size_passed = False
            size_details.append(
                f"Funding need {profile.funding_need_tnd:,.0f} TND exceeds cap {program.max_investment_tnd:,.0f} TND"
            )
        if program.min_investment_tnd and profile.funding_need_tnd < program.min_investment_tnd:
            size_passed = False
            size_details.append(
                f"Funding need {profile.funding_need_tnd:,.0f} TND below min threshold {program.min_investment_tnd:,.0f} TND"
            )

    traces.append(
        RuleTraceEntry(
            program_id=program.id,
            step="size",
            passed=size_passed,
            criterion="size_and_investment_limits",
            details="; ".join(size_details) if size_details else "Size and investment requirements met",
        )
    )
    if not size_passed:
        reasons.extend(size_details)

    # 4. Need Check
    need_passed = _matches_need(program, profile.need)
    traces.append(
        RuleTraceEntry(
            program_id=program.id,
            step="need",
            passed=need_passed,
            criterion="need_matching",
            details=(
                f"Need '{profile.need}' compatible with program '{program.id}' ({program.program_type})"
                if need_passed
                else f"Need '{profile.need}' incompatible with program '{program.id}' ({program.program_type})"
            ),
        )
    )
    if not need_passed:
        reasons.append(f"Program type '{program.program_type}' does not match requested need '{profile.need}'")

    # 5. Specific Conditions Check
    cond_passed = True
    cond_details = []

    # Innovation
    if program.requires_innovation and profile.is_innovative is False:
        cond_passed = False
        cond_details.append("Program strictly requires innovation or technological novelty")

    # Startup Label
    if program.requires_label and profile.has_startup_label is False:
        cond_passed = False
        cond_details.append("Program requires an active Startup Label (Loi 2018-20)")

    # Graduate diploma
    if program.requires_graduate and profile.is_graduate is False:
        cond_passed = False
        cond_details.append("Program requires founder to hold a university degree or certified vocational training")

    # Regional development zone
    if program.allowed_governorates:
        if not profile.governorate:
            cond_passed = False
            cond_details.append("Program requires location in a designated regional development zone (ZDR)")
        else:
            norm_gov = _normalize(profile.governorate)
            gov_match = any(norm_gov in _normalize(g) for g in program.allowed_governorates)
            if not gov_match:
                cond_passed = False
                cond_details.append(
                    f"Governorate '{profile.governorate}' is not an eligible regional development zone"
                )

    traces.append(
        RuleTraceEntry(
            program_id=program.id,
            step="conditions",
            passed=cond_passed,
            criterion="specific_eligibility_predicates",
            details="; ".join(cond_details) if cond_details else "All specific eligibility conditions verified",
        )
    )
    if not cond_passed:
        reasons.extend(cond_details)

    eligible = len(reasons) == 0
    return eligible, reasons, traces


def match_programs(
    profile: AidProfile, catalog: list[AidProgram] | None = None
) -> dict[str, Any]:
    """Run deterministic matching over all programs for a founder profile."""
    programs_pool = catalog if catalog is not None else CATALOG
    eligible_programs: list[AidProgram] = []
    excluded_programs: list[dict[str, Any]] = []
    all_traces: list[RuleTraceEntry] = []
    checklists: list[DocumentChecklist] = []

    for program in programs_pool:
        eligible, reasons, traces = evaluate_program(program, profile)
        all_traces.extend(traces)
        if eligible:
            eligible_programs.append(program)
            checklists.append(
                DocumentChecklist(
                    program_id=program.id,
                    program_name=program.name,
                    required_documents=program.required_documents,
                    official_form_link=program.official_form_link,
                )
            )
        else:
            excluded_programs.append(
                {
                    "program_id": program.id,
                    "name": program.name,
                    "reasons": reasons,
                    "source_file": program.source_file,
                    "source_page": program.source_page,
                }
            )

    handoff = detect_law_handoff(profile.free_text)

    return {
        "eligible_programs": eligible_programs,
        "excluded_programs": excluded_programs,
        "rule_trace": all_traces,
        "document_checklists": checklists,
        "handoff": handoff,
    }
