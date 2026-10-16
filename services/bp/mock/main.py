"""Mock bp service: fixture responses on the real endpoints (rule 4).

The orchestrator builds against this, then swaps the real service in by changing
one URL in .env. Run:  uvicorn mock.main:app --port 8104
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI

from app import storage
from app.contract import Artifact, Response, Request

FIX = Path(__file__).parent / "fixtures"
app = FastAPI(title="bp mock")


def _report_ref() -> str:
    return storage.put((FIX / "bp_report.json").read_bytes())


@app.get("/health")
def health():
    return {"status": "ok", "module": "bp", "mock": True}


@app.get("/v1/meta")
def meta():
    return {"module": "bp", "contract_version": "mock", "mock": True, "modes": ["review", "draft_section"]}


@app.post("/v1/run")
def run(req: Request):
    if not (req.file_ref or (req.options or {}).get("answers") or req.profile):
        return Response(**json.loads((FIX / "abstain.json").read_text()), request_id=req.request_id)
    data = json.loads((FIX / "review_ok.json").read_text())
    data["request_id"] = req.request_id
    data["artifacts"] = [Artifact(kind="json", file_ref=_report_ref(), label="bp_report").model_dump()]
    return Response(**data)


@app.post("/v1/questionnaire")
def questionnaire(body: dict):
    return json.loads((FIX / "questionnaire.json").read_text())


@app.post("/v1/eval")
def evaluate():
    return {"mock": True, "suites": {}}
