"""Run the 15 pitch cases (docx and pdf) through the pipeline and compare with answer_key.csv.

high_risk maps to the key's 'fraudulent'. These cases were used to tune the rule weights,
so the result is a development result, not evidence of accuracy on unseen plans.
Run:  python eval/run_pitch_eval.py            (no model: rules only)
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "eval" / "datasets" / "pitch_cases"
MAP = {"high_risk": "fraudulent", "bad": "bad", "moderate": "moderate", "good": "good"}


def main(verbose: bool = True) -> float:
    from app import storage
    from app.contract import Request
    from app.llm import LLMClient
    from app.pipeline import run
    import json

    key = {r["case"]: r["expected_label"] for r in csv.DictReader((DATA / "answer_key.csv").open(encoding="utf-8"))}
    ok = total = 0
    conf: Counter = Counter()
    for fmt in ("docx", "pdf"):
        for case, exp in key.items():
            f = DATA / fmt / f"{case}.{fmt}"
            ref = storage.put(f.read_bytes())
            r = run(Request(request_id=f"{case}-{fmt}", query="review", file_ref=ref, lang="en", options={"llm": False}),
                    LLMClient(api_key="", cache=False))
            rep = json.loads(storage.read([a.file_ref for a in r.artifacts if a.label == "bp_report"][0]))
            got = MAP[rep["assessment"]["verdict"]]
            total += 1
            ok += got == exp
            conf[(exp, got)] += 1
            if verbose and got != exp:
                print(f"MISS {case}.{fmt}: expected {exp}, got {got} score={rep['assessment']['score']} "
                      f"fraud={rep['assessment']['fraud_weight']} weak={rep['assessment']['weak_weight']} str={rep['assessment']['strength_count']}")
    if verbose:
        print(f"accuracy {ok}/{total} = {ok/total:.2f}")
        for (e, g), n in sorted(conf.items()):
            print(f"  expected {e:11s} got {g:11s} {n}")
    return ok / total


if __name__ == "__main__":
    main()
