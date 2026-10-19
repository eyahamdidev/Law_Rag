"""Tests for the P3 deterministic rule engine and catalog matching."""

import pytest
from app.modules.aid.catalog import CATALOG, get_program
from app.modules.aid.rules_engine import detect_law_handoff, match_programs
from app.config import REPO_ROOT
from app.schemas.aid import AidProfile


def test_catalog_loaded_and_valid():
    """Verify that catalog loads programs with required provenance and conditions."""
    assert len(CATALOG) >= 5
    for program in CATALOG:
        assert program.id
        assert program.name
        assert program.provider
        assert program.program_type in {"grant", "loan", "tax_incentive", "guarantee", "mixed"}
        assert len(program.stages) > 0
        assert program.source_file, f"Program {program.id} missing source_file"
        assert program.source_page is not None, f"Program {program.id} missing source_page"


def test_catalog_provenance_paths_exist():
    """Catalog references must point to checked-in corpus files."""
    for program in CATALOG:
        assert (REPO_ROOT / program.source_file).is_file(), program.id
        for local_file in program.local_files:
            assert (REPO_ROOT / local_file).is_file(), f"{program.id}: {local_file}"


def test_stage_filtering():
    """Creation profile matches creation programs and excludes extension-only programs."""
    profile = AidProfile(stage="creation", need="financing")
    result = match_programs(profile)
    eligible_ids = {p.id for p in result["eligible_programs"]}

    assert "bfpme-creation" in eligible_ids
    assert "bfpme-extension" not in eligible_ids


def test_sector_exclusion_for_bfpme():
    """Retail / traditional commerce is excluded from BFPME."""
    profile = AidProfile(stage="creation", sector="commerce_detail", need="loan")
    result = match_programs(profile)
    eligible_ids = {p.id for p in result["eligible_programs"]}

    assert "bfpme-creation" not in eligible_ids

    # Check rule trace records the exclusion
    traces = [t for t in result["rule_trace"] if t.program_id == "bfpme-creation" and t.step == "sector"]
    assert len(traces) == 1
    assert traces[0].passed is False


def test_innovation_condition_for_startup_act():
    """Non-innovative projects cannot qualify for Startup Act."""
    profile_non_innovative = AidProfile(stage="creation", sector="software", is_innovative=False)
    result = match_programs(profile_non_innovative)
    eligible_ids = {p.id for p in result["eligible_programs"]}
    assert "startup-act" not in eligible_ids

    profile_innovative = AidProfile(stage="creation", sector="software", is_innovative=True)
    result_innovative = match_programs(profile_innovative)
    eligible_innovative_ids = {p.id for p in result_innovative["eligible_programs"]}
    assert "startup-act" in eligible_innovative_ids


def test_unverified_cap_is_not_applied():
    """The BTS 150k TND cap is not in its cited source: kept as unverified, never used to exclude."""
    bts = next(p for p in CATALOG if p.id == "bts-jeunes-diplomes-fonapram")
    assert bts.max_investment_tnd is None
    assert bts.unverified["max_investment_tnd"] == 150000

    profile_large = AidProfile(stage="creation", funding_need_tnd=500000, need="loan", is_graduate=True)
    result_large = match_programs(profile_large)
    assert "bts-jeunes-diplomes-fonapram" in {p.id for p in result_large["eligible_programs"]}


def test_active_investment_limits_are_still_applied():
    """A limit kept in its active field still excludes (the engine itself is unchanged)."""
    capped = next(p for p in CATALOG if p.id == "bts-jeunes-diplomes-fonapram").model_copy(update={"max_investment_tnd": 150000})
    profile_large = AidProfile(stage="creation", funding_need_tnd=500000, need="loan", is_graduate=True)
    assert not match_programs(profile_large, catalog=[capped])["eligible_programs"]


def test_regional_zone_governorates_follow_annex_2():
    """Annexe 2 of décret 2017-389 also lists Tozeur, Bizerte, Sfax and Sousse; names match the extractor's."""
    for governorate in ("tozeur", "sidi bouzid", "sfax"):
        profile = AidProfile(stage="creation", sector="industrie", governorate=governorate, need="grant")
        assert "investment-regional-premium" in {p.id for p in match_programs(profile)["eligible_programs"]}, governorate


def test_regional_development_zone_matching():
    """Regional development premium requires an eligible governorate."""
    profile_eligible_region = AidProfile(
        stage="creation", sector="industrie", governorate="kasserine", need="grant"
    )
    result_eligible = match_programs(profile_eligible_region)
    assert "investment-regional-premium" in {p.id for p in result_eligible["eligible_programs"]}

    profile_tunis = AidProfile(
        stage="creation", sector="industrie", governorate="tunis", need="grant"
    )
    result_tunis = match_programs(profile_tunis)
    assert "investment-regional-premium" not in {p.id for p in result_tunis["eligible_programs"]}


def test_document_checklists_attached():
    """Eligible programs must include required documents checklist."""
    profile = AidProfile(stage="creation", sector="industrie", need="loan")
    result = match_programs(profile)
    checklists = {c.program_id: c for c in result["document_checklists"]}

    assert "bfpme-creation" in checklists
    bfpme_chk = checklists["bfpme-creation"]
    assert len(bfpme_chk.required_documents) > 0
    assert any("CIN" in doc for doc in bfpme_chk.required_documents)
    assert bfpme_chk.official_form_link.endswith(".doc")


def test_statute_question_handoff_detection():
    """Questions asking about statute/law articles return handoff to Law (P1)."""
    assert detect_law_handoff("Que dit l'article 6 de la loi 2016-71 ?") is not None
    handoff = detect_law_handoff("الفصل 8 من القانون عدد 20 لسنة 2018")
    assert handoff is not None
    assert handoff.to == "law"

    # Non-legal question should not trigger handoff
    assert detect_law_handoff("Quels sont les financements disponibles pour ma startup ?") is None
