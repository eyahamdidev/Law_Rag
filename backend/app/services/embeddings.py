"""bge-m3 embeddings.

Use Ollama's embedding endpoint first. A local sentence-transformers load is
the fallback and is left commented in requirements.txt because it installs PyTorch.
"""

from app.config import settings


class EmbeddingClient:
    model_name = "bge-m3"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or settings.ollama_base_url

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            f"{self.model_name} embeddings are not connected ({self.base_url})."
        )
