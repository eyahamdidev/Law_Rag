"""Retrieved passage contract, shared by every agent that searches the corpus."""

from typing import Literal

from pydantic import BaseModel, Field

RetrievalMode = Literal["dense", "bm25", "hybrid"]


class Passage(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    path: str
    corpora: list[str]
    domain: str
    language: str
    page_start: int
    page_end: int
    act: str | None = None
    article: str | None = None
    part: int = 1
    parts: int = 1
    publication_date: str | None = None
    publisher_url: str | None = None
    text: str
    score: float
    score_kind: str = Field(
        description="rrf, cosine, bm25 or rerank. Relevance to the query, not legal correctness."
    )

    def citation_label(self) -> str:
        bits = [self.act or self.title]
        if self.article:
            bits.append(f"art. {self.article}")
        pages = f"p. {self.page_start}" if self.page_start == self.page_end else f"pp. {self.page_start}-{self.page_end}"
        bits.append(pages)
        return ", ".join(bits)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    corpora: list[str] | None = None
    domains: list[str] | None = None
    k: int = Field(default=5, ge=1, le=20)
    mode: RetrievalMode | None = None
    strategy: str | None = None
    rerank: bool | None = None


class SearchResponse(BaseModel):
    query: str
    strategy: str
    mode: RetrievalMode
    reranked: bool
    passages: list[Passage]
