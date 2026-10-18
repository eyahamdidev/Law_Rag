"""Keyword plus multilingual dense retrieval.

    dense   e5 vectors in Qdrant (the deck's baseline when paired with fixed chunks)
    bm25    keyword search over the same chunks
    hybrid  both lists fused with Reciprocal Rank Fusion, k=60

RRF uses ranks, not raw scores, so cosine similarities and BM25 scores never
have to be put on one scale. Candidates can then go through the cross-encoder
(rerank.py). Its pool alternates between the lists (rank 1 of each, then rank 2,
...) rather than taking the RRF top: RRF halves the score of a chunk that only
one retriever finds, so a dense 5th place with no keyword match fell to RRF
rank 20-24 and never reached the reranker (measured on "capital minimum d'une
SA": art. 161). Same pool size, so the same rerank cost. The result is at most k distinct passages: one per document
article (or per page for documents without articles), filtered by corpus and
domain when the caller knows them.
"""

import logging

from app.config import settings
from app.modules.rag.ingestion.pipeline import load_chunks
from app.modules.rag.retrieval.bm25 import get_bm25
from app.modules.rag.retrieval.rerank import rerank as cross_rerank
from app.schemas.common import ModuleStatus, TraceStep
from app.schemas.rag import Passage, RetrievalMode

logger = logging.getLogger(__name__)

RRF_K = 60
CANDIDATES = 30
RERANK_POOL = 20

_rows_by_id: dict[str, dict[str, dict]] = {}


def _rows(strategy: str) -> dict[str, dict]:
    if strategy not in _rows_by_id:
        _rows_by_id[strategy] = {row["chunk_id"]: row for row in load_chunks(strategy)}
    return _rows_by_id[strategy]


def _dense(query: str, strategy: str, corpora, domains, limit: int, model: str | None = None) -> list[tuple[dict, float]]:
    from app.services.embeddings import get_embedder
    from app.services.vectorstore import get_store

    try:
        store = get_store()
        embedder = get_embedder(model)
        if not store.exists(strategy, embedder.model_name):
            return []
        vector = embedder.embed_query(query)
        hits = store.search(strategy, vector, corpora=corpora, domains=domains, limit=limit, model=embedder.model_name)
    except Exception as error:  # vector store locked or down: keyword search still answers
        logger.warning("dense retrieval unavailable, using BM25 only: %s", error)
        return []
    rows = _rows(strategy)
    return [(rows.get(payload["chunk_id"], payload), score) for payload, score in hits]


def _fuse(*ranked_lists: list[tuple[dict, float]]) -> list[tuple[dict, float]]:
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, (row, _) in enumerate(ranked):
            key = row["chunk_id"]
            rows[key] = row
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
    order = sorted(scores, key=scores.get, reverse=True)
    return [(rows[key], scores[key]) for key in order]


def _distinct_key(row: dict) -> tuple:
    if row.get("article"):
        return row["doc_id"], row.get("act"), row["article"]
    return row["doc_id"], row["page_start"]


def _passage(row: dict, score: float, kind: str) -> Passage:
    fields = Passage.model_fields
    data = {key: row[key] for key in fields if key in row}
    return Passage(**data, score=round(score, 4), score_kind=kind)


def search(
    query: str,
    *,
    corpora: list[str] | None = None,
    domains: list[str] | None = None,
    k: int = 5,
    mode: RetrievalMode | None = None,
    strategy: str | None = None,
    rerank: bool | None = None,
    embedding_model: str | None = None,
) -> list[Passage]:
    mode = mode or settings.retrieval_mode
    strategy = strategy or settings.chunk_strategy
    rerank = settings.use_reranker if rerank is None else rerank
    lists = _candidate_lists(query, mode, strategy, corpora, domains, embedding_model)
    return _rank(query, lists, mode, rerank, k)


def search_many(
    queries: list[str],
    *,
    rerank_query: str,
    corpora: list[str] | None = None,
    domains: list[str] | None = None,
    k: int = 5,
    rerank: bool | None = None,
) -> list[Passage]:
    """Several phrasings of one need (planner's French query, founder's words).

    Candidates from every query are fused with RRF, then reranked once against
    `rerank_query`. Reranking is the slow step, so this costs one rerank instead
    of one per query.
    """
    mode = settings.retrieval_mode
    strategy = settings.chunk_strategy
    rerank = settings.use_reranker if rerank is None else rerank
    lists = [
        ranked
        for q in dict.fromkeys(q.strip() for q in queries if q and q.strip())
        for ranked in _candidate_lists(q, mode, strategy, corpora, domains, None)
    ]
    return _rank(rerank_query, lists, "hybrid", rerank, k)


def _candidate_lists(query, mode, strategy, corpora, domains, embedding_model) -> list[list[tuple[dict, float]]]:
    """One ranked list per retriever used by `mode`."""
    lists = []
    if mode in ("dense", "hybrid"):
        lists.append(_dense(query, strategy, corpora, domains, CANDIDATES, embedding_model))
    if mode in ("bm25", "hybrid"):
        lists.append(get_bm25(strategy).search(query, corpora=corpora, domains=domains, limit=CANDIDATES))
    return lists


def _rank(query: str, lists: list[list[tuple[dict, float]]], mode: str, rerank: bool, k: int) -> list[Passage]:
    if rerank and any(lists):
        return _select(cross_rerank(query, _interleave(lists, RERANK_POOL)), "rerank", k)
    if mode == "dense" and len(lists) == 1:
        return _select(lists[0], "cosine", k)
    if mode == "bm25" and len(lists) == 1:
        return _select(lists[0], "bm25", k)
    return _select(_fuse(*lists), "rrf", k)


def _interleave(lists: list[list[tuple[dict, float]]], size: int) -> list[dict]:
    """Rank 1 of every list, then rank 2 of every list, ... until `size` distinct chunks."""
    pool, seen = [], set()
    for rank in range(max((len(ranked) for ranked in lists), default=0)):
        for ranked in lists:
            if rank < len(ranked) and ranked[rank][0]["chunk_id"] not in seen:
                seen.add(ranked[rank][0]["chunk_id"])
                pool.append(ranked[rank][0])
                if len(pool) == size:
                    return pool
    return pool


def _select(ranked: list[tuple[dict, float]], kind: str, k: int) -> list[Passage]:
    passages, seen = [], set()
    for row, score in ranked:
        key = _distinct_key(row)
        if key in seen:
            continue
        seen.add(key)
        passages.append(_passage(row, score, kind))
        if len(passages) == k:
            break
    return passages


def retrieve(
    question: str,
    domains: list[str] | None = None,
    *,
    corpora: list[str] | None = None,
    k: int = 5,
) -> tuple[list[Passage], TraceStep]:
    """Search plus a trace step, for agents and the workflow."""
    if not _rows(settings.chunk_strategy):
        return [], TraceStep(
            module="rag.retrieval",
            status=ModuleStatus.placeholder,
            detail="No index built yet. Run the ingestion pipeline.",
        )
    passages = search(question, corpora=corpora, domains=domains, k=k)
    scope = ", ".join(corpora or []) or "all corpora"
    return passages, TraceStep(
        module="rag.retrieval",
        status=ModuleStatus.ok,
        detail=(
            f"{len(passages)} passages ({settings.retrieval_mode}, {settings.chunk_strategy} chunks, "
            f"{scope}{'; domains ' + ', '.join(domains) if domains else ''})."
        ),
    )
