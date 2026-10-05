"""Cited-answer questions."""

from fastapi import APIRouter

from app.graph.workflow import run_question
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    return run_question(body.question.strip())
