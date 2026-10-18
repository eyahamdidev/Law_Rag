"""Liveness and the module map."""

import httpx
from fastapi import APIRouter

from app.config import settings
from app.services.llm import PROVIDERS
from app.agents.registry import cards
from app.modules.registry import modules as module_map
from app.schemas.agents import AgentCard
from app.schemas.common import HealthResponse, ModuleInfo

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app="tunisian-legal-financial-assistant",
        environment=settings.app_env,
    )


@router.get("/health/llm")
def llm_health() -> dict:
    """Is each provider's key accepted, and do our configured models still exist?

    Lists the provider's models (no generation, so no tokens or quota used). Catches
    a revoked key, and a model the provider has withdrawn (a 404 at answer time).
    Keys are never returned. Used by the n8n daily health check.
    """
    providers = {}
    for name in ("groq", "gemini"):
        spec = PROVIDERS[name]
        key = spec["key"]()
        wanted = sorted({spec[role]() for role in ("main", "fast", "compose") if spec[role]()})
        if not key:
            providers[name] = {"status": "not_configured", "models": wanted}
            continue
        try:
            response = httpx.get(spec["base_url"].rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=15)
        except httpx.HTTPError as error:
            providers[name] = {"status": "unreachable", "error": error.__class__.__name__, "models": wanted}
            continue
        if response.status_code != 200:
            status = "key_rejected" if response.status_code in (401, 403) else f"http_{response.status_code}"
            providers[name] = {"status": status, "models": wanted}
            continue
        listed = {m.get("id", "").removeprefix("models/") for m in response.json().get("data", [])}
        missing = [m for m in wanted if m not in listed]
        providers[name] = {"status": "ok" if not missing else "model_missing", "models": wanted, "missing": missing}
    ok = any(p["status"] == "ok" for p in providers.values())
    return {"status": "ok" if ok else "down", "providers": providers}


@router.get("/modules", response_model=list[ModuleInfo])
def modules() -> list[ModuleInfo]:
    return module_map()


@router.get("/agents", response_model=list[AgentCard])
def agents() -> list[AgentCard]:
    return cards()
