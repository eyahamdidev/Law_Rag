"""Frozen HTTP service for deterministic aid matching."""

from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

SERVICE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = SERVICE_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.aid.extractor import extract_profile  # noqa: E402
from app.modules.aid.rules_engine import detect_law_handoff  # noqa: E402
from app.modules.aid.matcher import match  # noqa: E402
from app.schemas.aid import AidProfile  # noqa: E402


class RunRequest(BaseModel):
    request_id: str | None = None
    question: str = ""
    profile: AidProfile | None = None
    language: str = "fr"


class ServiceResponse(BaseModel):
    request_id: str | None = None
    status: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    signals: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    handoff: dict[str, str] | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float


app = FastAPI(title="P3 Aid Service", version="1.0.0")


def _answer(match_response: Any) -> tuple[str, list[dict[str, Any]]]:
    citations = [
        {
            "doc_id": f"grants:{program.id}",
            "path": program.source_file,
            "page": program.source_page,
            "title": program.name,
        }
        for program in match_response.programs
    ]
    if not match_response.programs:
        return "Aucun programme ne correspond aux critères déterministes fournis.", citations
    names = ", ".join(program.name for program in match_response.programs)
    return f"Programmes compatibles selon les règles déterministes : {names}.", citations


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "aid", "catalog_programs": len(_catalog())}


def _catalog() -> list[Any]:
    from app.modules.aid.catalog import CATALOG

    return CATALOG


@app.get("/v1/meta")
def meta() -> dict[str, Any]:
    return {
        "module": "aid",
        "contract_version": "v1",
        "service_port": 8103,
        "eligibility": "deterministic",
        "catalog_programs": len(_catalog()),
        "prompt_versions": {
            "aid.extract_profile": "v2",
            "aid.explain_match": "v2",
        },
    }


@app.post("/v1/run", response_model=ServiceResponse)
def run(request: RunRequest) -> ServiceResponse:
    started = perf_counter()
    handoff = detect_law_handoff(request.question)
    if handoff:
        answer = "Cette question porte sur le contenu d'un texte juridique et doit être traitée par le service law."
        return ServiceResponse(
            request_id=request.request_id,
            status="ok",
            answer=answer,
            handoff={"to": handoff.to, "question": handoff.question},
            signals=[{"type": "handoff", "target": "law"}],
            trace=[{"module": "aid.handoff", "status": "ok"}],
            latency_ms=round((perf_counter() - started) * 1000, 3),
        )

    profile = request.profile
    missing_fields: list[str] = []
    extraction_ref = "provided"
    if profile is None:
        profile, missing_fields, extraction_ref = extract_profile(request.question)
    response = match(profile)
    answer, citations = _answer(response)
    status = "abstain" if missing_fields and not response.programs else "ok"
    signals = [{"type": "missing_field", "field": field} for field in missing_fields]
    signals.append({"type": "eligibility", "mode": "deterministic"})
    trace = [{"module": step.module, "status": step.status.value, "detail": step.detail} for step in response.trace]
    trace.append({"module": "aid.intake", "status": "ok", "detail": extraction_ref})
    return ServiceResponse(
        request_id=request.request_id,
        status=status,
        answer=answer,
        citations=citations,
        signals=signals,
        artifacts=[
            {
                "type": "rule_trace",
                "count": len(response.rule_trace),
                "entries": [entry.model_dump() for entry in response.rule_trace],
            }
        ],
        handoff=None,
        trace=trace,
        latency_ms=round((perf_counter() - started) * 1000, 3),
    )
