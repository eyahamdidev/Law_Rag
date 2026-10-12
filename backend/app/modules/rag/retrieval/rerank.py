"""Cross-encoder rerank of the fused candidates.

jina-reranker-v2-base-multilingual reads the query and passage together,
which catches paraphrases that neither BM25 nor the bi-encoder ranks high.
It costs roughly 1-2 s for 20 candidates on CPU, so it is off by default
(USE_RERANKER) and measured separately in the retrieval evaluation.
The score shown in the UI is relevance, not the probability that a legal
answer built on the passage is correct.
"""

from app.config import settings
from app.services.embeddings import onnx_providers

_model = None


def _reranker():
    global _model
    if _model is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        _model = TextCrossEncoder(
            settings.reranker_model, cache_dir=str(settings.data_dir / "models"), providers=onnx_providers()
        )
    return _model


def rerank(question: str, rows: list[dict]) -> list[tuple[dict, float]]:
    if not rows:
        return []
    # Small batches: a 4 GB GPU runs out of memory at fastembed's default of 64 pairs.
    scores = list(_reranker().rerank(question, [row["embed_text"] for row in rows], batch_size=4))
    ranked = sorted(zip(rows, scores), key=lambda pair: pair[1], reverse=True)
    return [(row, float(score)) for row, score in ranked]
