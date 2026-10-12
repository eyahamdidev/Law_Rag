"""Multilingual passage and query embeddings with ONNX Runtime, without PyTorch.

The deck planned bge-m3. fastembed (ONNX Runtime) does not ship a dense
bge-m3, so the candidates are the multilingual e5 family (trained on French
and Arabic among ~100 languages). Measured on this project's chunks:

                            dim   CPU (8 threads)   GTX 1050 4 GB (DirectML)
    multilingual-e5-small   384    7.4 chunks/s      23.1 chunks/s
    multilingual-e5-base    768    2.7 chunks/s      12.2 chunks/s
    multilingual-e5-large  1024    0.5 chunks/s       3.8 chunks/s (batch 4; batch 8 runs out of VRAM)

EMBEDDING_DEVICE=dml uses the GPU through DirectML (Windows, any DirectX 12
card, no CUDA install). Without onnxruntime-directml it falls back to CPU,
so the same code runs in Docker and on teammates' laptops.

The retrieval evaluation compares them; the default follows its result.
e5 expects "query: " and "passage: " prefixes. Vectors are cached in SQLite
by (model, text) hash, so re-indexing unchanged chunks costs nothing.
"""

import hashlib
import sqlite3
import threading
from collections.abc import Iterable

import numpy as np

from app.config import settings

# e5-small and e5-base publish ONNX weights on the Hub but are not in
# fastembed's built-in list, so they are registered here.
_CUSTOM_MODELS = {
    "intfloat/multilingual-e5-small": 384,
    "intfloat/multilingual-e5-base": 768,
}
_registered: set[str] = set()


def _register(model_name: str) -> None:
    if model_name not in _CUSTOM_MODELS or model_name in _registered:
        return
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    try:
        TextEmbedding.add_custom_model(
            model=model_name,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=model_name),
            dim=_CUSTOM_MODELS[model_name],
            model_file="onnx/model.onnx",
        )
    except ValueError:  # already registered in this process
        pass
    _registered.add(model_name)


def onnx_providers() -> list | None:
    """Execution providers for fastembed: DirectML GPU when configured and installed."""
    if settings.embedding_device != "dml":
        return None
    import onnxruntime

    if "DmlExecutionProvider" not in onnxruntime.get_available_providers():
        return None
    return [("DmlExecutionProvider", {"device_id": settings.embedding_device_id}), "CPUExecutionProvider"]


def model_slug(model_name: str) -> str:
    return model_name.split("/")[-1].replace("multilingual-", "").replace("-", "_")


class EmbeddingClient:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.embedding_model
        self._model = None
        self._lock = threading.Lock()
        cache_path = settings.data_dir / "embedding_cache.sqlite"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(cache_path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vec BLOB)")

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            _register(self.model_name)
            self._model = TextEmbedding(
                self.model_name, cache_dir=str(settings.data_dir / "models"), providers=onnx_providers()
            )
        return self._model

    @property
    def is_e5(self) -> bool:
        return "e5" in self.model_name.lower()

    def _key(self, text: str) -> str:
        return hashlib.sha1(f"{self.model_name}\0{text}".encode("utf-8")).hexdigest()

    def _embed(self, texts: list[str]) -> list[np.ndarray]:
        batch_size = settings.embedding_batch_size
        keys = [self._key(text) for text in texts]
        found: dict[str, np.ndarray] = {}
        for start in range(0, len(keys), 500):
            batch = keys[start : start + 500]
            marks = ",".join("?" * len(batch))
            rows = self._db.execute(f"SELECT key, vec FROM vectors WHERE key IN ({marks})", batch)
            found.update((key, np.frombuffer(blob, dtype=np.float32)) for key, blob in rows)
        missing = [i for i, key in enumerate(keys) if key not in found]
        if missing:
            with self._lock:
                vectors = self.model.embed([texts[i] for i in missing], batch_size=batch_size)
                for index, vector in zip(missing, vectors):
                    vector = np.asarray(vector, dtype=np.float32)
                    found[keys[index]] = vector
                    self._db.execute(
                        "INSERT OR REPLACE INTO vectors VALUES (?, ?)", (keys[index], vector.tobytes())
                    )
                self._db.commit()
        return [found[key] for key in keys]

    def embed_passages(self, texts: Iterable[str]) -> list[np.ndarray]:
        prefix = "passage: " if self.is_e5 else ""
        return self._embed([prefix + text for text in texts])

    def embed_query(self, text: str) -> np.ndarray:
        prefix = "query: " if self.is_e5 else ""
        return self._embed([prefix + text])[0]

    @property
    def dimension(self) -> int:
        return int(self.embed_query("dimension probe").shape[0])


_clients: dict[str, EmbeddingClient] = {}


def get_embedder(model_name: str | None = None) -> EmbeddingClient:
    name = model_name or settings.embedding_model
    if name not in _clients:
        _clients[name] = EmbeddingClient(name)
    return _clients[name]
