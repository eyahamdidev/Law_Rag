"""Run every plan in <root>/good, <root>/moderate, <root>/bad and compare the verdict with the folder name.

    python eval/run_folder_eval.py test_plans

good -> good, moderate -> moderate, bad -> bad or high_risk. Files in fraud_language/ are ignored.
Folder names are YOUR labels, so the table is only as good as those labels. No model key is used.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
OK = {"good": {"good"}, "moderate": {"moderate"}, "bad": {"bad", "high_risk"}}


def main(root: str) -> None:
    from app import storage
    from app.contract import Request
    from app.llm import LLMClient
    from app.pipeline import run

    conf: Counter = Counter()
    hits = total = 0
    for label in OK:
        for f in sorted((Path(root) / label).glob("*")):
            if f.suffix.lower() not in (".docx", ".pdf", ".txt", ".xlsx"):
                continue
            r = run(Request(request_id=f.stem, query="review", file_ref=storage.put(f.read_bytes()), lang="en", options={"llm": False}),
                    LLMClient(api_key="", cache=False))
            rep = json.loads(storage.read(next(a.file_ref for a in r.artifacts if a.label == "bp_report")))
            a = rep.get("assessment") or {}
            got = a.get("verdict", "none")
            total += 1
            hits += got in OK[label]
            conf[(label, got)] += 1
            flags = [x["rule"] for x in a.get("flags", [])][:4]
            print(f"{'ok  ' if got in OK[label] else 'MISS'} {label:9s} -> {got:9s} {f.name}  score={a.get('score')} flags={flags}")
    if not total:
        sys.exit("No plans found. Expected folders good/, moderate/, bad/ with .docx, .pdf or .txt files.")
    print(f"\n{hits}/{total} verdicts match the folder labels")
    for (lab, got), n in sorted(conf.items()):
        print(f"  folder {lab:9s} verdict {got:9s} {n}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test_plans")
