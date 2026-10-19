"""Tests never call hosted APIs or a live local model by accident."""
import pytest
from app.config import settings

@pytest.fixture(autouse=True)
def no_live_model(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "local_llm_enabled", False)
    monkeypatch.setattr(settings, "legal_web_fallback_enabled", False)
    monkeypatch.setattr(settings, "retrieval_mode", "bm25")
    monkeypatch.setattr(settings, "use_reranker", False)
