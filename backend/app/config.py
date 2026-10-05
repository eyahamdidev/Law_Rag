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

    ollama_base_url: str = "http://localhost:11434"
    qdrant_url: str = "http://localhost:6333"
    mlflow_tracking_uri: str = "http://localhost:5000"

    def resolve(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return (REPO_ROOT / path).resolve()


settings = Settings()
settings.law_corpus_dir = settings.resolve(settings.law_corpus_dir)
settings.aid_corpus_dir = settings.resolve(settings.aid_corpus_dir)
settings.fraud_data_dir = settings.resolve(settings.fraud_data_dir)
