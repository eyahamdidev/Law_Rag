"""Financial section drafts must not claim break-even when projections are incomplete."""

from app.agents import writer as W
from app.templates import load_template


def test_template_draft_incomplete_no_break_even():
    sec = next(s for s in load_template("bfpme_creation")["sections"] if s["id"] == "financial_projections")
    derived = {"years": ["Y1", "Y2", "Y3"], "revenue": [50000.0, 400000.0, 3000000.0],
               "cogs": [None, None, None], "net_income": [None, None, None], "incomplete": True,
               "assumptions": ["Projection incomplete: salaries and other costs not provided."]}
    text = W.template_draft(sec, {"currency": "TND"}, derived, "en").lower()
    assert "incomplete" in text
    assert "break-even" not in text
    assert "net result" not in text
