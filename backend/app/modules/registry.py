"""Module map shown by GET /api/modules and the web shell.

Agents come from app/agents/registry.py; this adds the shared pipeline pieces.
"""

from app.agents.registry import cards
from app.config import settings
from app.modules.rag.ingestion.pipeline import load_chunks
from app.schemas.common import ModuleInfo, ModuleStatus
from app.services.llm import get_llm


def modules() -> list[ModuleInfo]:
    llm = ModuleStatus.ok if get_llm().available else ModuleStatus.placeholder
    index = ModuleStatus.ok if load_chunks(settings.chunk_strategy) else ModuleStatus.placeholder
    shared = [
        ModuleInfo(id="intake", pillar="shared", role="PDF text, vision OCR of scans and photos, language.", status=llm),
        ModuleInfo(id="orchestrator.plan", pillar="shared", role="LLM planner with keyword fallback: agents, sub-tasks, French search query, clarification.", status=ModuleStatus.ok),
        ModuleInfo(id="rag.ingestion", pillar="shared", role="Extract, repair, chunk by article, keep document, act, article and page.", status=index),
        ModuleInfo(id="rag.retrieval", pillar="shared", role=f"{settings.retrieval_mode} search ({settings.chunk_strategy} chunks, {settings.embedding_model}).", status=index),
        ModuleInfo(id="orchestrator.verify", pillar="shared", role="Citation validity in code, claim support by LLM.", status=llm),
        ModuleInfo(id="orchestrator.compose", pillar="shared", role="Global citation numbers, removes unsupported claims, one reply.", status=ModuleStatus.ok),
    ]
    agents = [
        ModuleInfo(
            id=f"agent.{card.id}",
            pillar="agents",
            role=f"{card.description} Owner: {card.owner}.",
            status=ModuleStatus.ok if card.status == "ready" else ModuleStatus.placeholder,
        )
        for card in cards()
    ]
    return shared + agents
