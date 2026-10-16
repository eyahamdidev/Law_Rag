"""Test the module without labelled plans: damage a plan on purpose and see if the damage is noticed.

Put any .docx plans in a folder (good ones are best: yours, a classmate's, a sample plan saved
from the web). For each plan this script makes variants, each with a known expected reaction:

  delete_market     remove the market/competition section     -> that section is reported missing or its score drops
  strip_numbers     remove every digit                        -> completeness drops
  ponzi_sentence    add a guaranteed-return, new-money line   -> a fraud-pattern flag appears
  bad_funding_table add a plan-of-financing table whose sources and uses differ -> 'sources_neq_uses'
  inflate_margin    add a projection with a 70% margin        -> a margin or net-margin signal

It also checks the untouched plan for false alarms. Run from services/bp:
    python scripts/mutation_test.py "C:\\path\\to\\folder_of_docx" [--out mutation_report.csv]
Limit: the 'ponzi_sentence' test reuses wording the rules were written for, so it only proves the rule
fires, not that it would catch a fraud written in other words. The other four tests are fairer.
No model key is used, so the result shows what the rule-based path catches. Nothing is sent anywhere.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import docx  # noqa: E402

MARKET = re.compile(r"march[eé]|market|concurren|competit|السوق", re.I)


def load(path: Path) -> docx.document.Document:
    return docx.Document(str(path))


def to_bytes(d) -> bytes:
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def is_heading(p) -> bool:
    name = (p.style.name if p.style is not None else "") or ""
    t = p.text.strip()
    return bool(t) and (name.lower().startswith(("heading", "titre", "title")) or (len(t) < 50 and not t.endswith((".", ",", ";")) and not re.search(r"\d", t)))


def delete_market(d) -> bool:
    paras, hit = d.paragraphs, None
    for i, p in enumerate(paras):
        if is_heading(p) and MARKET.search(p.text):
            hit = i
            break
    if hit is None:
        return False
    j = hit + 1
    while j < len(paras) and not is_heading(paras[j]):
        j += 1
    for p in paras[hit:j]:
        p._element.getparent().remove(p._element)
    return True


def strip_numbers(d) -> bool:
    for p in d.paragraphs:
        for r in p.runs:
            r.text = re.sub(r"\d+", "", r.text)
    return True


def ponzi_sentence(d) -> bool:
    d.add_paragraph("Investors receive a guaranteed 22 percent annual return paid monthly. New investor deposits are used to fund monthly payouts "
                    "when collections are delayed. Investor funds are held in an operating account alongside company funds. An audit has not been done.")
    return True


def bad_funding_table(d) -> bool:
    d.add_paragraph("Plan de financement")
    t = d.add_table(rows=4, cols=4)
    for r, row in enumerate([["Emplois", "Montant", "Ressources", "Montant"], ["Investissements materiels", "70 000", "Fonds propres", "40 000"],
                             ["Besoin en fonds de roulement", "10 000", "Credit bancaire", "20 000"], ["Total emplois", "80 000", "Total ressources", "60 000"]]):
        for c, v in enumerate(row):
            t.cell(r, c).text = v
    return True


def inflate_margin(d) -> bool:
    d.add_paragraph("Projections financieres")
    t = d.add_table(rows=5, cols=4)
    rows = [["", "Year 1", "Year 2", "Year 3"], ["Revenue", "100 000", "400 000", "1 200 000"], ["Purchases", "10 000", "30 000", "90 000"],
            ["Payroll", "10 000", "20 000", "40 000"], ["Net result", "75 000", "330 000", "1 050 000"]]
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            t.cell(r, c).text = v
    return True


MUTATIONS = {"delete_market": delete_market, "strip_numbers": strip_numbers, "ponzi_sentence": ponzi_sentence,
             "bad_funding_table": bad_funding_table, "inflate_margin": inflate_margin}


def review(data: bytes, tag: str) -> dict:
    from app import storage
    from app.contract import Request
    from app.llm import LLMClient
    from app.pipeline import run

    ref = storage.put(data)
    r = run(Request(request_id=tag, query="review", file_ref=ref, lang="en", options={"llm": False}), LLMClient(api_key="", cache=False))
    rep = json.loads(storage.read(next(a.file_ref for a in r.artifacts if a.label == "bp_report")))
    secs = {s["section_id"]: s for s in rep["completeness"]["sections"]}
    return {"completeness": rep["completeness"]["overall"], "kinds": {s.kind for s in r.signals}, "ids": {s.id for s in r.signals},
            "verdict": (rep.get("assessment") or {}).get("verdict"), "market": secs.get("market_analysis") or secs.get("market"),
            "fraud_flags": {f["rule"] for f in (rep.get("assessment") or {}).get("flags", []) if f["group"] == "fraud"}}


def expectation(name: str, base: dict, new: dict) -> tuple[bool, str]:
    if name == "delete_market":
        a, b = (base["market"] or {}).get("score", 0), (new["market"] or {}).get("score", 0)
        return b < a or (new["market"] or {}).get("status") == "missing", f"market score {a} -> {b}"
    if name == "strip_numbers":
        return new["completeness"] < base["completeness"], f"completeness {base['completeness']} -> {new['completeness']}"
    if name == "ponzi_sentence":
        added = new["fraud_flags"] - base["fraud_flags"]
        return bool(added), f"new fraud flags: {sorted(added)}; verdict {base['verdict']} -> {new['verdict']}"
    if name == "bad_funding_table":
        return "sources_neq_uses" in new["kinds"] and "sources_neq_uses" not in base["kinds"], "sources_neq_uses " + ("raised" if "sources_neq_uses" in new["kinds"] else "NOT raised")
    if name == "inflate_margin":
        hit = {k for k in new["kinds"] - base["kinds"] if k in ("margin_above_sector", "impossible_margin", "growth_implausible")}
        return bool(hit), f"new signals: {sorted(new['kinds'] - base['kinds'])}"
    return False, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="mutation_report.csv")
    a = ap.parse_args()
    plans = sorted(Path(a.folder).glob("*.docx"))
    if not plans:
        sys.exit("No .docx files found in that folder. Save plans as .docx first.")
    rows, caught, total = [], 0, 0
    for p in plans:
        base = review(p.read_bytes(), p.stem)
        rows.append([p.name, "(untouched)", "", f"verdict {base['verdict']}, completeness {base['completeness']}, fraud flags {sorted(base['fraud_flags'])}"])
        for name, fn in MUTATIONS.items():
            d = load(p)
            if not fn(d):
                rows.append([p.name, name, "n/a", "plan has no matching section to damage"])
                continue
            new = review(to_bytes(d), f"{p.stem}-{name}")
            ok, detail = expectation(name, base, new)
            total += 1
            caught += ok
            rows.append([p.name, name, "CAUGHT" if ok else "MISSED", detail])
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows([["plan", "variant", "result", "detail"], *rows])
    print(f"{caught}/{total} deliberate problems were noticed. Details in {a.out}.")
    for r in rows:
        if r[2] == "MISSED":
            print("MISSED:", r[0], r[1], "-", r[3])


if __name__ == "__main__":
    main()
