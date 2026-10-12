"""Direct passage search, for the evidence viewer and for teammates' agents over HTTP."""

from fastapi import APIRouter

from app.config import settings
from app.modules.rag.retrieval.hybrid import search
from app.schemas.rag import SearchRequest, SearchResponse

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
def search_passages(body: SearchRequest) -> SearchResponse:
    passages = search(
        body.query,
        corpora=body.corpora,
        domains=body.domains,
        k=body.k,
        mode=body.mode,
        strategy=body.strategy,
        rerank=body.rerank,
    )
    return SearchResponse(
        query=body.query,
        strategy=body.strategy or settings.chunk_strategy,
        mode=body.mode or settings.retrieval_mode,
        reranked=settings.use_reranker if body.rerank is None else body.rerank,
        passages=passages,
    )
