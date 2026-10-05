"""Cited-answer contract for the legal and financial RAG flow."""

from pydantic import BaseModel, Field

from app.schemas.common import ModuleStatus, TraceStep


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class Citation(BaseModel):
    document_id: str
    title: str
    page: int | None = None
    article: str | None = None
    version_date: str | None = None
    score: float | None = None
    score_meaning: str = "retrieval relevance, not legal correctness"


class WorkerDraft(BaseModel):
    domain: str
    status: ModuleStatus
    summary: str
    claims: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    status: ModuleStatus
    intent: str
    domains: list[str]
    language: str
    needs_clarification: bool
    answer: str
    abstained: bool
    citations: list[Citation]
    trace: list[TraceStep]
