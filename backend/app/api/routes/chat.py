"""Cited-answer questions."""

from fastapi import APIRouter, Header

from app.graph.workflow import run_question
from app.modules.orchestrator import profile as session_profile
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, x_session_id: str | None = Header(default=None)) -> ChatResponse:
    question = body.question.strip()
    # What the founder says here is useful to the business-plan module later.
    session_profile.merge(x_session_id, session_profile.hints_from_text(question))
    return run_question(question)
