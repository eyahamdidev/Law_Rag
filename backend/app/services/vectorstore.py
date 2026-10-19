"""Qdrant collections for passage vectors and their metadata.

Embedded mode (a folder under data/qdrant) is the default so the project runs
without Docker. Set QDRANT_URL to use the server from docker-compose instead;
the API calls are identical. One collection per (chunking strategy,
embedding model), so the retrieval evaluation can compare them on the same
questions.
"""

import atexit
import threading

from qdrant_client import QdrantClient, models

from app.config import settings
from app.services.embeddings import model_slug

COLLECTION_PREFIX = "passages"


def collection_name(strategy: str, model: str | None = None) -> str:
    return f"{COLLECTION_PREFIX}_{strategy}_{model_slug(model or settings.embedding_model)}"


class VectorStore:
    def __init__(self, url: str | None = None) -> None:
        url = settings.qdrant_url if url is None else url
        # Embedded Qdrant is not thread-safe; parallel agents share it through this lock.
        self._lock = threading.Lock()
        if url:
            self.client = QdrantClient(url=url)
        else:
            path = settings.data_dir / "qdrant"
            path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
        atexit.register(self.client.close)

    def recreate(self, strategy: str, dimension: int, model: str | None = None) -> None:
        name = collection_name(strategy, model)
        if self.client.collection_exists(name):
            self.client.delete_collection(name)
        self.client.create_collection(
            name,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )
        for field in ("corpora", "domain", "language", "doc_id"):
            try:
                self.client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
            except Exception:  # embedded mode ignores payload indexes
                pass

    def upsert(self, strategy: str, ids: list[str], vectors: list, payloads: list[dict], model: str | None = None) -> None:
        self.client.upsert(
            collection_name(strategy, model),
            points=[
                models.PointStruct(id=pid, vector=list(map(float, vec)), payload=payload)
                for pid, vec, payload in zip(ids, vectors, payloads)
            ],
        )

    def exists(self, strategy: str, model: str | None = None) -> bool:
        return self.client.collection_exists(collection_name(strategy, model))

    def search(
        self,
        strategy: str,
        vector,
        *,
        corpora: list[str] | None = None,
        domains: list[str] | None = None,
        limit: int = 20,
        model: str | None = None,
    ) -> list[tuple[dict, float]]:
        must = []
        if corpora:
            must.append(models.FieldCondition(key="corpora", match=models.MatchAny(any=corpora)))
        if domains:
            must.append(models.FieldCondition(key="domain", match=models.MatchAny(any=domains)))
        with self._lock:
            hits = self.client.query_points(
                collection_name(strategy, model),
                query=list(map(float, vector)),
                query_filter=models.Filter(must=must) if must else None,
                limit=limit,
                with_payload=True,
            ).points
        return [(hit.payload, float(hit.score)) for hit in hits]


_store: VectorStore | None = None
_store_lock = threading.Lock()


def get_store() -> VectorStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = VectorStore()
    return _store
