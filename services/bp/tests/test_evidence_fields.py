"""Optional evidence fields (traction, IP, awards, permits) in one schema."""

from app.plan_facts import PlanFacts
from app.profile import merge_context
from app.questionnaire import clean_answers


def test_evidence_fields_normalise_and_validate():
    c = clean_answers({"traction_note": "12 pilot farms signed in 2025.", "ip_note": "Patent pending on sensor firmware.",
                       "awards_note": "Startup Act label applied.", "permits_note": "None yet — agri IoT exempt."})
    assert "traction_note" in c.values
    ctx = merge_context(None, c.values, None)
    pf = PlanFacts.from_context(ctx)
    assert pf.traction_note.startswith("12 pilot")
    assert pf.ip_note and pf.permits_note
