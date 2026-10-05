"""State carried across the planned LangGraph nodes."""

from dataclasses import dataclass, field

from app.schemas.common import TraceStep


@dataclass
class QuestionState:
    question: str
    language: str = "en"
    intent: str = "rag"
    domains: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    passages: list[dict] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
