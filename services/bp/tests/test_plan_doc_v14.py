"""Plan document v14: pure parts only (no model). The six-section narrative opens the plan; contradictions become questions."""

import io

from docx import Document

from app import plan_doc


def _text(blob: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(blob)).paragraphs)


def test_narrative_opens_the_plan_and_open_items_are_merged():
    fp = {"sections": [{"id": "executive_summary", "title": "Executive Summary", "status": "ok",
                        "text": "Polaris sells soil sensors. [NEEDED: how many farms?]"},
                       {"id": "market_opportunity", "title": "Market", "status": "error", "text": ""}],
          "open_items": ["how many farms?"], "verdict": "Draft with gaps"}
    sec = {"id": "team", "title": "Team", "blocks": [("p", "Aya - CEO")], "missing": []}
    out = _text(plan_doc.build_plan_docx("Polaris", [sec], None, "en", [], final_plan=fp))
    assert out.index("Executive Summary") < out.index("Team")
    assert "Draft with gaps" in out and "how many farms?" in out
    assert "Market" not in out.split("Team")[0].split("Executive Summary")[1]  # a failed section is not printed


def test_no_final_plan_still_builds():
    sec = {"id": "team", "title": "Team", "blocks": [("p", "Aya - CEO")], "missing": []}
    assert "Aya - CEO" in _text(plan_doc.build_plan_docx("Polaris", [sec], None, "en", []))


def test_executive_summary_synthesis_from_facts():
    sec = {"id": "executive_summary", "title": {"en": "Executive summary", "fr": "Résumé", "ar": ""},
           "questions": ["project_name", "sector", "problem", "solution"]}
    comp = {"id": "executive_summary", "title": "Executive summary", "blocks": [], "missing": ["Legal form"]}
    plan_doc.build_executive_summary(comp, sec, {"project_name": "Polaris", "sector": "Tech", "problem": "Pain X.",
                                                 "solution": "Platform Y.", "funding_need_amount": 50000}, None, "en")
    text = plan_doc.section_plaintext(comp)
    assert "Polaris" in text and "Pain X" in text and "Platform Y" in text
    assert "50 000" in text or "50000" in text.replace(" ", "")


def test_consistency_notes_are_questions_not_corrections():
    base = {"total_investment": 8000, "funding_need_amount": 3000, "funding_instrument": "loan", "loan_amount": 3000}
    assert plan_doc.consistency_notes(base, "en") == []
    n = plan_doc.consistency_notes({**base, "funding_need_amount": 9000}, "en")
    assert len(n) == 1 and "larger than the total investment" in n[0]
    n = plan_doc.consistency_notes({**base, "funding_instrument": "none"}, "fr")
    assert n and "Aucun financement externe" in n[0]
    n = plan_doc.consistency_notes({**base, "funding_instrument": "grant"}, "en")
    assert any("grant" in x and "loan" in x for x in n)
