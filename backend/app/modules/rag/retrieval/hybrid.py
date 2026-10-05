"""Keyword plus multilingual dense retrieval.

Baseline to beat: fixed-size chunks, dense-only, same held-out questions.
Planned stack: BM25 (rank-bm25) and bge-m3 vectors in Qdrant, filtered by
domain and verified version, then a reranker. Return at most five distinct
passages. Fewer when fewer useful matches exist.
"""

from app.schemas.common import ModuleStatus, TraceStep


def retrieve(question: str, domains: list[str]) -> tuple[list[dict], TraceStep]:
    domain_label = ", ".join(domains) if domains else "unspecified"
    step = TraceStep(
        module="rag.retrieval",
        status=ModuleStatus.placeholder,
        detail=f"No index query for domains: {domain_label}.",
    )
    return [], step
