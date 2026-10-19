"""Runtime paths and planned service endpoints."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        extra="ignore",
    )

    app_env: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    law_corpus_dir: Path = REPO_ROOT / "law" / "TUNISIA_LEGAL_BUSINESS_CORPUS"
    aid_corpus_dir: Path = REPO_ROOT / "grants_and_financial_aids"
    fraud_data_dir: Path = REPO_ROOT / "fraud_detection"
    business_plan_dir: Path = REPO_ROOT / "business_plan"

    # Generated artefacts: chunks, embedding cache, local Qdrant, OCR text.
    data_dir: Path = REPO_ROOT / "data"

    # Retrieval. Empty qdrant_url means embedded Qdrant under data_dir.
    embedding_model: str = "intfloat/multilingual-e5-base"
    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    chunk_strategy: str = "structural"
    retrieval_mode: str = "hybrid"
    use_reranker: bool = True
    qdrant_url: str = ""
    # "cpu", or "dml" for a GPU through DirectML on Windows (pip install onnxruntime-directml).
    # DirectML numbers adapters itself: on a laptop with Intel + NVIDIA, the NVIDIA card is usually 1.
    embedding_device: str = "cpu"
    embedding_device_id: int = 1
    embedding_batch_size: int = 16

    # LLM providers. Both expose an OpenAI-compatible endpoint.
    llm_provider: str = "groq"
    llm_fallback_provider: str = "gemini"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_fast_model: str = "qwen/qwen3.8-27b"
    groq_compose_model: str = "openai/gpt-oss-20b"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_fast_model: str = "gemini-3.5-flash-lite"
    llm_timeout_s: float = 60.0
    local_llm_enabled: bool = False
    local_llm_base_url: str = "http://127.0.0.1:11434/v1"
    local_llm_model: str = "local-legal"
    legal_web_fallback_enabled: bool = False
    # Fraud detection service (fraud_detection/), run separately: python -m fraud_detection serve --port 8100
    fraud_service_url: str = "http://127.0.0.1:8100"
    fraud_timeout_s: float = 60.0
    # Business plan service (services/bp/), run separately on port 8104. Uploads are shared by reference.
    uploads_dir: Path = REPO_ROOT / "data" / "uploads"
    bp_service_url: str = "http://localhost:8104"
    bp_timeout_s: float = 360.0
    # gpt-oss only: hidden reasoning tokens count toward max_tokens. low | medium | high
    llm_reasoning_effort: str = "low"

    ollama_base_url: str = "http://localhost:11434"
    mlflow_tracking_uri: str = "http://localhost:5000"

    def resolve(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return (REPO_ROOT / path).resolve()


settings = Settings()
settings.law_corpus_dir = settings.resolve(settings.law_corpus_dir)
settings.aid_corpus_dir = settings.resolve(settings.aid_corpus_dir)
settings.fraud_data_dir = settings.resolve(settings.fraud_data_dir)
settings.business_plan_dir = settings.resolve(settings.business_plan_dir)
settings.data_dir = settings.resolve(settings.data_dir)
settings.uploads_dir = settings.resolve(settings.uploads_dir)
