"""One-off live LLM audit (not CI). Writes services/bp/tmp/live_audit.txt."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env"
if ENV.exists():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from app import pipeline as pl, prompts, storage  # noqa: E402
from app.config import model_for, settings  # noqa: E402
from app.contract import Request  # noqa: E402
from app.llm import LLMClient  # noqa: E402

POLARIS = {
    "project_name": "Polaris", "sector": "Recruitment web platform", "stage": "creation",
    "problem": "Students find internships through scattered channels.",
    "solution": "A platform that matches interns and companies.",
    "target_customers": "Students and SMEs in Tunisia.",
    "competitors": "Handshake, LinkedIn, Indeed, Glassdoor, Welcome to the Jungle, ErasmusIntern, Teal, Huntr",
    "market_size_note": "The global recruitment market is 40.6 billion USD (Statista, 2025).",
    "governorate": "Sfax", "horizon_years": "5",
    "revenue_by_year": "20000, 60000, 150000, 300000, 500000",
    "cogs_by_year": "1000, 2500, 5000, 9000, 15000",
}
SOIL = (
    "SoilSense\nSoilSense sells connected soil sensors that tell farmers when to irrigate.\n"
    "Revenue: 50 000 TND in year 1, 400 000 TND in year 2 and 3 000 000 TND in year 3.\n"
    "We are seeking 500 000 TND to finance the first production run.\n"
    "The market outlook is very positive and the market is worth 4.6 billion TND.\n"
)

OUT = Path(__file__).resolve().parents[1] / "tmp" / "live_audit.txt"


def _meta() -> dict:
    pfw = prompts.load("final_writer", version=6)
    ppw = prompts.load("plan_writer", version=2)
    return {
        "llm_base_url": settings.llm_base_url,
        "llm_model_main": model_for("llm_main"),
        "llm_model_fast": model_for("llm_fast"),
        "prompt_final_writer": prompts.ref(pfw),
        "prompt_plan_writer": prompts.ref(ppw),
        "llm_available": LLMClient().available,
    }


def _summarise(label: str, r) -> dict:
    rep = json.loads(storage.read(next(a.file_ref for a in r.artifacts if a.label == "bp_report")))
    plan = next((a for a in r.artifacts if a.label == "business_plan"), None)
    return {
        "label": label,
        "status": r.status,
        "critique_n": len((rep.get("critique") or {}).get("weaknesses") or []),
        "sections": len(rep.get("generated_plan", {}).get("sections") or []),
        "final_plan": bool(rep.get("final_plan")),
        "polished_sections": sum(1 for s in rep.get("generated_plan", {}).get("sections") or [] if s.get("polished")),
        "incomplete_financials": bool((rep.get("financials") or {}).get("incomplete")),
        "plan_docx_ref": plan.file_ref if plan else None,
    }


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    lines = ["# Live LLM audit (manual, not CI)", json.dumps(_meta(), indent=2)]
    llm = LLMClient()
    if not llm.available:
        lines.append("SKIP: LLM_API_KEY empty or endpoint unreachable.")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return
    for label, req in (
        ("polaris_chat", Request(request_id="live-p", lang="en", options={"answers": POLARIS, "generate_plan": True, "llm": True})),
        ("soilsense_upload", Request(request_id="live-s", lang="en", options={"answers": {}, "generate_plan": True, "llm": True},
                                     file_ref=storage.put(SOIL.encode()))),
    ):
        try:
            r = pl.run(req, llm=llm)
            lines.append(json.dumps(_summarise(label, r), indent=2))
        except Exception as exc:  # noqa: BLE001
            lines.append(f"{label} ERROR: {exc.__class__.__name__}: {exc}")
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
