"""Local chat and vision through Ollama."""

from app.config import settings


class OllamaClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or settings.ollama_base_url

    def generate(self, prompt: str) -> str:
        raise NotImplementedError(
            f"Ollama generation is not connected ({self.base_url})."
        )

    def describe_page(self, image_bytes: bytes) -> str:
        raise NotImplementedError("Ollama vision OCR is not connected.")
