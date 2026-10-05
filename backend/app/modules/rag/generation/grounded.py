"""Draft an answer that may only use retrieved passages.

Connect this to services/llm.py (Ollama). If the passages are empty, the
composer abstains instead of calling the model.
"""

from app.schemas.common import ModuleStatus, TraceStep


def draft_from_passages(question: str, passages: list[dict]) -> TraceStep:
    return TraceStep(
        module="rag.generation",
        status=ModuleStatus.placeholder,
        detail="Ollama generation is not connected.",
    )
