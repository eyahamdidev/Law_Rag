"""Parser-only diagnostics on plan_dataset (keyword + optional LLM)."""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2].parent / "plan_dataset"
    use_llm = "--llm" in sys.argv
    manifest = {}
    for r in csv.DictReader((data / "manifest.csv").open(encoding="utf-8-sig")):
        manifest[r["file"]] = r.get("language") or "fr"

    from app.agents.common import Trace
    from app.agents import parser as parser_agent
    from app.agents import reviewer
    from app.intake import read_document
    from app.llm import LLMClient
    from app.masking import Masker
    from app.templates import load_template

    key = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
    llm = LLMClient(api_key=key if use_llm else "", cache=False)
    tpl = load_template("bfpme_creation")
    req_ids = [s["id"] for s in tpl["sections"] if s["required"]]

    for fpath in sorted((data / "raw").rglob("*.docx")):
        rel = fpath.relative_to(data / "raw").as_posix()
        lang = manifest.get(rel, "fr")
        doc = read_document(fpath.read_bytes())
        heads = sum(1 for b in doc.blocks if b.kind == "heading")
        plan = parser_agent.parse(
            doc,
            tpl,
            llm=llm,
            masker=Masker(),
            lang=lang,
            trace=Trace(),
            mode="auto" if use_llm else "keywords",
        )
        mapped = len(plan.sections)
        unmapped = len(plan.unmapped)
        reviews = reviewer.review_all(tpl, plan.sections, lang=lang, llm=LLMClient(api_key="", cache=False), masker=Masker(), trace=Trace(), use_llm=False)
        miss_req = [rv.section_id for rv in reviews if rv.required and rv.status == "missing"]
        chars = sum(len(v.get("text", "")) for v in plan.sections.values())
        print(
            f"{rel}: blocks={len(doc.blocks)} heads={heads} mapped_secs={mapped} unmapped={unmapped} "
            f"text_chars={chars} miss_req={len(miss_req)}/{len(req_ids)} {miss_req[:5]}"
        )


if __name__ == "__main__":
    main()
