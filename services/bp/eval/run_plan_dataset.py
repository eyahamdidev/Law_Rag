"""Evaluate plan_dataset labels vs pipeline (rules-only by default).

    python eval/run_plan_dataset.py [path/to/plan_dataset] [--llm]
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXP_OK = {"bad": {"bad", "high_risk"}, "good": {"good"}, "moderate": {"moderate"}}


def main() -> None:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else Path(__file__).resolve().parents[2].parent / "plan_dataset"
    use_llm = "--llm" in sys.argv
    labels_path = data / "labels.csv"
    labels = {r["file"]: r["verdict"] for r in csv.DictReader(labels_path.open(encoding="utf-8-sig"))}
    manifest = {}
    mp = data / "manifest.csv"
    if mp.exists():
        for r in csv.DictReader(mp.open(encoding="utf-8-sig")):
            manifest[r["file"]] = r.get("language") or "fr"

    from app import storage
    from app.contract import Request
    from app.llm import LLMClient
    from app.pipeline import run

    key = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
    if use_llm and not key:
        sys.exit("Set LLM_API_KEY or GROQ_API_KEY for --llm")
    llm = LLMClient(api_key=key if use_llm else "", cache=False)

    ok = total = 0
    for fpath in sorted((data / "raw").rglob("*.docx")):
        rel = fpath.relative_to(data / "raw").as_posix()
        exp = labels.get(rel)
        if not exp:
            continue
        lang = manifest.get(rel, "fr")
        if lang not in ("fr", "en", "ar"):
            lang = "fr"
        ref = storage.put(fpath.read_bytes())
        r = run(
            Request(request_id=fpath.stem, query="review", file_ref=ref, lang=lang, options={"llm": use_llm}),
            llm,
        )
        rep = json.loads(storage.read([a.file_ref for a in r.artifacts if a.label == "bp_report"][0]))
        got = rep["assessment"]["verdict"]
        match = got in EXP_OK[exp]
        total += 1
        ok += int(match)
        secs = rep["completeness"]["sections"]
        miss = sum(1 for s in secs if s["status"] == "missing")
        weak = sum(1 for s in secs if s["status"] == "weak")
        tag = "OK  " if match else "MISS"
        print(
            f"{tag} exp={exp:8s} got={got:10s} score={rep['assessment']['score']:3d} "
            f"compl={rep['completeness']['overall']:3d} miss={miss:2d} weak={weak:2d} lang={lang} {rel}"
        )
    if not total:
        sys.exit(f"No labeled docx under {data / 'raw'}")
    print(f"\n{ok}/{total} verdict match (llm={use_llm})")


if __name__ == "__main__":
    main()
