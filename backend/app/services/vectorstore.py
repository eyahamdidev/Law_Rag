"""Qdrant collection for passage vectors and the metadata in PASSAGE_FIELDS."""

from app.config import settings


class VectorStore:
    collection = "tunisia_legal_passages"

    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.qdrant_url

    def upsert(self, points: list[dict]) -> None:
        raise NotImplementedError(f"Qdrant upsert is not connected ({self.url}).")

    def search(self, vector: list[float], domains: list[str], limit: int = 5) -> list[dict]:
        raise NotImplementedError(f"Qdrant search is not connected ({self.url}).")
