"""bp service (P4): business-plan review and drafting. Port 8104.

Endpoints: the four every module exposes (/health, /v1/meta, /v1/run, /v1/eval)
plus one additive, read-only helper, POST /v1/questionnaire, which the UI needs
to render the guided questionnaire with prefilled answers. It is listed in
/v1/meta so P5 can approve it in the contract review.
"""

from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import FastAPI, Request as HttpRequest
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import prompts
from app.config import DEFAULT_MODELS, SERVICE_ROOT, model_for, settings
from app.contract import CONTRACT_VERSION, ErrorInfo, ModuleError, Request, Response
from app.pipeline import run as run_pipeline
from app.questionnaire import BANK
from app.questionnaire_view import view as questionnaire_view
from app.templates import TEMPLATE_IDS

app = FastAPI(title="bp service", version="0.1.0")

STATUS = {"BAD_INPUT": 400, "UNSUPPORTED_FILE": 415, "MODEL_UNAVAILABLE": 503, "TIMEOUT": 504, "INTERNAL": 500}


def _error(request_id: str, code: str, message: str, t0: float) -> JSONResponse:
    body = Response(request_id=request_id, status="error", error=ErrorInfo(code=code, message=message),
                    latency_ms=int((time.perf_counter() - t0) * 1000))
    return JSONResponse(body.model_dump(), status_code=STATUS[code])


_reach_cache: dict[str, tuple[float, bool]] = {}


def _llm_reachable() -> bool | None:
    if not settings.llm_enabled:
        return None
    hit = _reach_cache.get("llm")
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    try:
        r = httpx.get(f"{settings.llm_base_url}/models", headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=2.0)
        ok = r.status_code < 500
    except httpx.HTTPError:
        ok = False
    _reach_cache["llm"] = (time.time(), ok)
    return ok


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "module": "bp", "llm_configured": settings.llm_enabled, "llm_reachable": _llm_reachable(),
            "note": "Without a model the service still runs: deterministic checks, keyword review, answer-based drafts."}


@app.get("/v1/meta")
def meta() -> dict:
    prompt_versions = {}
    for folder in sorted((SERVICE_ROOT / "prompts" / "bp").iterdir()):
        if folder.is_dir():
            prompt_versions[folder.name] = sorted(p.stem for p in folder.glob("v*.yaml"))
    from app.agents.guidance import passages

    return {
        "module": "bp", "contract_version": CONTRACT_VERSION, "port": 8104,
        "endpoints": ["GET /health", "GET /v1/meta", "POST /v1/run", "POST /v1/eval", "POST /v1/questionnaire (additive, pending P5 approval)", "POST /v1/chat (additive, chat-style questionnaire, pending P5 approval)"],
        "modes": ["review", "draft_section"],
        "input_methods": ["upload (file_ref)", "questionnaire (options.answers)", "orchestrator profile (profile)"],
        "models": {role: model_for(role) for role in DEFAULT_MODELS},
        "prompt_versions": prompt_versions,
        "corpus": {"templates": list(TEMPLATE_IDS), "questions": len(BANK), "guidance_passages": len(passages()),
                   "templates_verified_against_official_model": False},
        "timeout_budget_s": settings.timeout_budget_s,
    }


@app.post("/v1/run")
async def run(req: Request):
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(asyncio.to_thread(run_pipeline, req), timeout=settings.timeout_budget_s)
    except asyncio.TimeoutError:
        return _error(req.request_id, "TIMEOUT", f"No answer within {settings.timeout_budget_s:g} s.", t0)
    except ModuleError as exc:
        return _error(req.request_id, exc.code, exc.message, t0)
    except Exception as exc:  # noqa: BLE001  degrade, never crash
        return _error(req.request_id, "INTERNAL", f"{exc.__class__.__name__}: {exc}"[:300], t0)
    return result


class QuestionnaireBody(BaseModel):
    lang: str = "fr"
    profile: dict | None = None
    answers: dict | None = None
    template: str | None = None


@app.post("/v1/questionnaire")
def questionnaire(body: QuestionnaireBody):
    try:
        return questionnaire_view(body.profile, body.answers, body.lang if body.lang in ("fr", "ar", "en") else "fr", body.template)
    except ModuleError as exc:
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=STATUS[exc.code])


class ChatBody(BaseModel):
    lang: str = "fr"
    profile: dict | None = None
    state: dict | None = None
    message: str | None = None
    action: str | None = None


@app.post("/v1/chat")
def chat(body: ChatBody):
    from app.interview import turn

    return turn(lang=body.lang, profile=body.profile, state=body.state, message=body.message, action=body.action)


class EvalBody(BaseModel):
    suite: str = Field(default="all", description="all | financial | sections | writer | merge")
    seed: int = 7
    n: int | None = None


@app.post("/v1/eval")
async def evaluate(body: EvalBody | None = None):
    from eval.run_eval import run_all

    b = body or EvalBody()
    try:
        return await asyncio.wait_for(asyncio.to_thread(run_all, b.suite, b.seed, b.n), timeout=settings.timeout_budget_s * 3)
    except asyncio.TimeoutError:
        return JSONResponse({"error": {"code": "TIMEOUT", "message": "Evaluation did not finish in time."}}, status_code=504)
