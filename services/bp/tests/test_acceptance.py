"""Acceptance tests from the master prompt, mapped to this repo's field ids.

Fixtures: SoilSense (upload) and Polaris (chat answers). Mocks only: no llm key is
set, so every step runs the deterministic path.
"""

from __future__ import annotations

import io
import json
import re

import docx

from app import pipeline as pl
from app import storage
from app.agents.critic import run_plan_rules
from app.config import SERVICE_ROOT
from app.contract import Request
from app.interview import parse_reply
from app.llm import LLMClient, LLMUnavailable

SOILSENSE_TEXT = (
    "SoilSense\n"
    "SoilSense sells connected soil sensors that tell farmers when to irrigate.\n"
    "Revenue: 50 000 TND in year 1, 400 000 TND in year 2 and 3 000 000 TND in year 3.\n"
    "We are seeking 500 000 TND to finance the first production run.\n"
    "The market outlook is very positive and the market is worth 4.6 billion TND.\n"
)

GAMELLE_TEXT = (
    "Gamelle\n"
    "Gamelle delivers balanced lunches to offices in Lyon.\n"
    "Each meal is priced at 9.50 EUR.\n"
    "We are raising 250 000 EUR. The 250 000 EUR will be used to buy kitchen equipment and fund the working capital.\n"
    "The plan is financed with 100 000 EUR of our own funds, a 75 000 EUR bank loan and a 75 000 EUR grant.\n"
    "Competitors: MiumMiam and Cantine Chez Nous.\n"
    "The team is 3 people.\n"
    "Risks: clients cancel orders; food waste; the delivery van breaks down.\n"
)

FACTUREPRO_TEXT = (
    "FacturePro\n"
    "FacturePro edits invoices for very small Moroccan companies.\n"
    "The subscription costs 99 MAD per month.\n"
)

GAMELLE_FACTS = {
    "project_name": "Gamelle", "sector": "Meal delivery", "stage": "creation",
    "pricing": "9.50 EUR per meal",
    "own_funds": 100000, "loan_amount": 75000, "grant_amount": 75000,
    "market_size_note": "Around 310 000 meals a year in the area, 38 000 office workers, 1 200 companies.",
    "headcount": 3,
    "competitors": "MiumMiam, Cantine Chez Nous",
    "risks": "- clients cancel orders\n- food waste\n- the delivery van breaks down",
    "currency": "EUR",
}


class StubLLM(LLMClient):
    """available=True so the extraction step runs; the canned facts stand in for the model. Anything else refuses."""

    def __init__(self, canned: dict):
        super().__init__(api_key="", cache=False, transport=object())
        self.canned = canned

    def chat_json(self, *, model, system, user, schema=None, images=None, max_tokens=2048):  # noqa: ARG002
        if "extract stated facts" in system:
            return dict(self.canned)
        raise LLMUnavailable("stub: extraction only")

SOILSENSE_TEXT = (
    "SoilSense\n"
    "SoilSense sells connected soil sensors that tell farmers when to irrigate.\n"
    "Revenue: 50 000 TND in year 1, 400 000 TND in year 2 and 3 000 000 TND in year 3.\n"
    "We are seeking 500 000 TND to finance the first production run.\n"
    "The market outlook is very positive and the market is worth 4.6 billion TND.\n"
)

POLARIS = {
    "project_name": "Polaris",
    "sector": "Recruitment web platform",
    "stage": "creation",
    "problem": "Students find internships through scattered channels.",
    "solution": "A platform that matches interns and companies.",
    "target_customers": "Students and SMEs in Tunisia.",
    "competitors": ("![image](https://www.google.com/s2/favicons?domain=handshake) Handshake +3, LinkedIn, Indeed, "
                    "Glassdoor, Welcome to the Jungle, ErasmusIntern, Teal, Huntr"),
    "market_size_note": "The global recruitment market is 40.6 billion USD (Statista, 2025).",
    "governorate": "Sfax",
    "horizon_years": "5",
    "revenue_by_year": "20000, 60000, 150000, 300000, 500000",
    "cogs_by_year": "1000, 2500, 5000, 9000, 15000",
}


def _run(req: Request, llm=None):
    return pl.run(req, llm)  # llm=None: the fully deterministic path


def _report(r) -> dict:
    return json.loads(storage.read(next(a.file_ref for a in r.artifacts if a.label == "bp_report")))


def _docx_text(r, label: str) -> str:
    art = next(a for a in r.artifacts if a.label == label)
    return "\n".join(p.text for p in docx.Document(io.BytesIO(storage.read(art.file_ref))).paragraphs)


def _docx_section_text(r, label: str, heading: str) -> str:
    """Text of one top-level section of the docx (headings and paragraphs; tables included via their cells)."""
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(storage.read(next(a.file_ref for a in r.artifacts if a.label == label))))
    out, inside = [], False
    for child in d.element.body.iterchildren():
        if child.tag.endswith("}p"):
            p = Paragraph(child, d)
            if p.style.name.startswith("Heading 1"):
                inside = p.text.strip().lower().startswith(heading.lower())
                continue
            if inside:
                out.append(p.text)
        elif child.tag.endswith("}tbl") and inside:
            for row in DocxTable(child, d).rows:
                out.append(" ".join(c.text for c in row.cells))
    return "\n".join(out)


def test_soilsense_upload_facts_and_open_items():
    r = _run(Request(request_id="soilsense", lang="en",
                     options={"answers": {}, "template": "bfpme_creation", "generate_plan": True},
                     file_ref=storage.put(SOILSENSE_TEXT.encode())))
    assert r.status == "ok"
    rep = _report(r)
    vals = rep["context"]["values"]
    assert vals["project_name"] == "SoilSense"
    assert vals["funding_need_amount"] == 500000
    assert vals.get("pricing") is None
    assert rep["financials"]["revenue"][:3] == [50000.0, 400000.0, 3000000.0]
    missing = " ".join(str(m) for s in rep["generated_plan"]["sections"] for m in s["missing"])
    for label in ("Project or company name", "Revenue per year", "External funding needed"):
        assert label not in missing, label
    dump = SERVICE_ROOT / "tmp" / "facts_soilsense.json"
    assert dump.exists() and json.loads(dump.read_text(encoding="utf-8"))["project_name"] == "SoilSense"


def test_polaris_governorate_rejected_and_reasked():
    value, err = parse_reply("governorate", "Tunisian", {})
    assert value is None and err  # the chat asks the question again
    value, err = parse_reply("governorate", "We will be based in Sfax", {})
    assert value == "Sfax" and err is None


def test_polaris_clean_answers_verbatim_and_honest_projection():
    r = _run(Request(request_id="polaris", lang="en",
                     options={"answers": POLARIS, "template": "bfpme_creation", "generate_plan": True}))
    assert r.status == "ok"
    blob = json.dumps(_report(r), ensure_ascii=False)
    vals = json.loads(blob)["context"]["values"]
    for name in ("Handshake", "LinkedIn", "Indeed", "Glassdoor", "Welcome to the Jungle", "ErasmusIntern", "Teal", "Huntr"):
        assert name in vals["competitors"], name
    for junk in ("favicons", "&#x", "ESPIRIT"):
        assert junk not in blob, junk
    assert not re.search(r"\bTunis\b", blob), "Tunis"  # "Tunisia" is fine, the city as an answer is not
    projection = _docx_section_text(r, "business_plan", "financial projections").lower()
    assert "incomplete" in projection
    assert "break-even" not in projection  # no break-even claim when salaries and other costs are missing
    plan_text = _docx_text(r, "business_plan")
    low = plan_text.lower()
    assert "40.6" in low and "statista" in low  # market figure and its source land in the plan
    assert "Polaris" in plan_text  # project name capitalization preserved
    exec_blob = _docx_section_text(r, "business_plan", "executive").lower()
    assert "scattered" in exec_blob or "internship" in exec_blob  # exec summary synthesised from stated problem


def test_soilsense_upload_pipeline_critic():
    r = _run(Request(request_id="soilsense-crit", lang="en",
                     options={"answers": {}, "template": "bfpme_creation", "generate_plan": True},
                     file_ref=storage.put(SOILSENSE_TEXT.encode())))
    weaknesses = _report(r).get("critique", {}).get("weaknesses", [])
    assert len(weaknesses) >= 2
    whys = " ".join(w["why"] for w in weaknesses)
    assert "price" in whys.lower() or "spent" in whys.lower()


def test_soilsense_critic_rules_quote_the_plan():
    text = ("SoilSense: revenue of 50 000 TND in year 1, 400 000 TND in year 2 and 3 000 000 TND in year 3. "
            "The market outlook is very positive and worth billions. The market is 4.6 billion TND. "
            "We are seeking 500 000 TND. The price will be set later.")
    values = {"funding_need_amount": 500000, "pricing": "later"}
    derived = {"years": ["Y1", "Y2", "Y3"], "revenue": [50000.0, 400000.0, 3000000.0]}
    rules = [w.why for w in run_plan_rules(text, values, derived)]
    quotes = [w.quote or "" for w in run_plan_rules(text, values, derived)]
    assert any("very positive" in q for q in quotes)
    assert any("billions" in q for q in quotes)
    assert any("grows 8.0x" in w for w in rules)  # every year pair above 3x
    assert any("grows 7.5x" in w for w in rules)  # year 2 -> year 3 included
    assert any("never says what it will be spent on" in w for w in rules)
    assert any("No price is stated" in w or "price" in w.lower() for w in rules)
    assert all(len(q.split()) <= 13 for q in quotes if q)  # max 12 words plus the ellipsis


def test_both_paths_same_section_list():
    chat = _run(Request(request_id="c1", lang="en", options={"answers": POLARIS, "template": "bfpme_creation"}))
    up = _run(Request(request_id="c2", lang="en",
                      options={"answers": {}, "template": "bfpme_creation"}, file_ref=storage.put(SOILSENSE_TEXT.encode())))
    ids_chat = [s["section_id"] for s in _report(chat)["completeness"]["sections"]]
    ids_up = [s["section_id"] for s in _report(up)["completeness"]["sections"]]
    assert ids_chat == ids_up


def test_gamelle_upload_facts_extracted_and_eur():
    r = _run(Request(request_id="gamelle", lang="en", options={"answers": {}, "generate_plan": True},
                     file_ref=storage.put(GAMELLE_TEXT.encode())), llm=StubLLM(GAMELLE_FACTS))
    assert r.status == "ok"
    vals = _report(r)["context"]["values"]
    assert vals["project_name"] == "Gamelle"
    assert vals["pricing"] == "9.50 EUR per meal"
    assert vals["funding_need_amount"] == 250000
    assert vals["currency"] == "EUR"
    assert vals["own_funds"] == 100000 and vals["loan_amount"] == 75000 and vals["grant_amount"] == 75000
    assert vals["headcount"] == 3
    assert "MiumMiam" in vals["competitors"] and vals["risks"].count("-") == 3
    missing = " ".join(str(m) for s in _report(r)["generated_plan"]["sections"] for m in s["missing"])
    for label in ("Pricing", "External funding needed", "Main risks", "Own funds", "Bank loan", "Grants"):
        assert label not in missing, label
    text = _docx_text(r, "business_plan")
    assert "9.50" in text and "310 000" in text and "38 000" in text and "1 200" in text
    assert " TND" not in text  # EUR everywhere: never converted, never mixed
    for false_finding in ("No price is stated", "never says what it will be spent on", "absent from the plan",
                          "is present but thin"):
        assert false_finding not in text, false_finding


def test_no_artisan_example_in_any_plan():
    texts = []
    texts.append(_docx_text(_run(Request(request_id="a1", lang="en", options={"answers": {}, "generate_plan": True},
                                         file_ref=storage.put(SOILSENSE_TEXT.encode()))), "business_plan"))
    texts.append(_docx_text(_run(Request(request_id="a2", lang="en", options={"answers": {}, "generate_plan": True},
                                         file_ref=storage.put(GAMELLE_TEXT.encode())), llm=StubLLM(GAMELLE_FACTS)), "business_plan"))
    texts.append(_docx_text(_run(Request(request_id="a3", lang="en", options={"answers": {}, "generate_plan": True},
                                         file_ref=storage.put(FACTUREPRO_TEXT.encode())), llm=StubLLM({"project_name": "FacturePro", "currency": "MAD", "pricing": "99 MAD per month"})), "business_plan"))
    for t in texts:
        assert "artisan" not in t.lower()


def test_facturepro_currency_mad():
    r = _run(Request(request_id="facturepro", lang="en", options={"answers": {}, "generate_plan": True},
                     file_ref=storage.put(FACTUREPRO_TEXT.encode())), llm=StubLLM({"project_name": "FacturePro", "currency": "MAD", "pricing": "99 MAD per month"}))
    vals = _report(r)["context"]["values"]
    assert vals["currency"] == "MAD"
    text = _docx_text(r, "business_plan")
    assert "99" in text and "MAD" in text and " TND" not in text


def test_draft_with_no_facts_never_calls_the_model():
    from app.agents import writer as W
    from app.masking import Masker
    from app.templates import load_template

    class Boom(StubLLM):
        def chat_json(self, **kw):  # any model call fails the test
            raise AssertionError("writer called the model with no facts")

    sec = next(s for s in load_template("bfpme_creation")["sections"] if s["id"] == "risks")
    d = W.draft_section(sec, values={}, derived=None, existing="", guidance=[], lang="en",
                        llm=Boom({}), masker=Masker(names=[]), trace=_trace())
    assert d.method != "model"
    assert W.MARKERS["en"] in d.text  # the deterministic placeholder stands, no invented content


def _trace():
    from app.agents.common import Trace

    return Trace()
