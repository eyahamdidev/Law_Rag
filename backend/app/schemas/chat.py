"""Chat contract: one founder message in, one verified and cited reply out."""

from pydantic import BaseModel, Field

from app.schemas.agents import AgentStatus, Citation, FounderProfile
from app.schemas.common import ModuleStatus, TraceStep
from app.schemas.legal import DraftRequest


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, description="Same id for every message of one founder")
    channel: str = Field(default="web", description="web, telegram, email... set by n8n")
    legal_contract: DraftRequest | None = None


class PlanStepOut(BaseModel):
    agent: str
    task: str
    search_query: str


class PlanOut(BaseModel):
    source: str
    steps: list[PlanStepOut]
    reason: str
    clarification: str | None = None
    out_of_scope: bool = False
    prompt_ref: str | None = None


class AgentSummary(BaseModel):
    agent: str
    status: AgentStatus
    answer: str
    missing_info: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str
    status: ModuleStatus
    language: str
    plan: PlanOut
    answer: str
    abstained: bool
    needs_clarification: bool
    citations: list[Citation]
    agents: list[AgentSummary]
    missing_info: list[str]
    profile: FounderProfile
    verification: dict
    composed_by: str
    latency_ms: float
    trace: list[TraceStep]
    artifacts: list[dict] = Field(default_factory=list)
