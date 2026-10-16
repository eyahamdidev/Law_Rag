"""Liveness and the module map."""

from fastapi import APIRouter

from app.config import settings
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


@router.get("/modules", response_model=list[ModuleInfo])
def modules() -> list[ModuleInfo]:
    return module_map()


@router.get("/agents", response_model=list[AgentCard])
def agents() -> list[AgentCard]:
    return cards()
