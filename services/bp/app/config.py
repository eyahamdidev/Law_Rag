"""Environment-driven settings. Nothing here is a secret default."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Settings:
    """Read lazily so tests can monkeypatch the environment."""

    @property
    def uploads_dir(self) -> Path:
        env = os.environ.get("UPLOADS_DIR")
        if env:
            return Path(env)
        # Run from the repo (no Docker): share the gateway's folder, <repo>/data/uploads.
        repo = SERVICE_ROOT.parents[1] if len(SERVICE_ROOT.parents) > 1 else None
        if repo is not None and (repo / "backend").is_dir():
            return repo / "data" / "uploads"
        return Path("/data/uploads")

    @property
    def llm_base_url(self) -> str:
        return _env("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")

    @property
    def llm_api_key(self) -> str:
        return _env("LLM_API_KEY", "")

    @property
    def llm_request_timeout_s(self) -> float:
        # Local models on a laptop are slow. Raise this together with BP_TIMEOUT_S.
        return float(_env("LLM_TIMEOUT_S", "45"))

    @property
    def llm_max_retries(self) -> int:
        return max(0, int(_env("LLM_MAX_RETRIES", "6")))

    @property
    def final_writer_section_pace_s(self) -> float:
        """Pause between per-section top-up calls to stay under Groq TPM limits."""
        return max(0.0, float(_env("BP_FINAL_WRITER_PACE_S", "3")))

    def llm_step(self, name: str) -> bool:
        """BP_LLM_STEPS=plan_writer,drafts limits the model to those steps (parser, reviewer, assessment, vision,
        drafts, plan_writer). Default: all. Useful on a slow local model: reading and judging plans stays rule-based and fast."""
        raw = _env("BP_LLM_STEPS", "all").strip().lower()
        return raw in ("", "all") or name in {x.strip() for x in raw.split(",")}

    @property
    def llm_json_mode(self) -> str:
        # "json_schema" (strict) or "json_object" depending on the model.
        return _env("LLM_JSON_MODE", "json_object")

    @property
    def llm_cache_path(self) -> Path:
        return Path(_env("LLM_CACHE_PATH", str(SERVICE_ROOT / ".cache" / "llm_cache.sqlite")))

    @property
    def llm_enabled(self) -> bool:
        return _env("BP_LLM", "auto").lower() != "off" and bool(self.llm_api_key)

    @property
    def ollama_url(self) -> str:
        return _env("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")

    @property
    def qdrant_url(self) -> str:
        return _env("QDRANT_URL", "http://qdrant:6333").rstrip("/")

    @property
    def use_vector_store(self) -> bool:
        return _env("BP_VECTOR_STORE", "auto").lower() != "off"

    @property
    def models_config(self) -> Path:
        return Path(_env("MODELS_CONFIG", str(SERVICE_ROOT.parents[1] / "config" / "models.yaml")))

    @property
    def timeout_budget_s(self) -> float:
        return float(_env("BP_TIMEOUT_S", "60"))

    @property
    def mlflow_uri(self) -> str:
        return _env("MLFLOW_TRACKING_URI", "")


settings = Settings()

DEFAULT_MODELS = {
    "llm_main": "llama-3.3-70b-versatile",
    "llm_fast": "llama-3.1-8b-instant",
    "llm_vision": "meta-llama/llama-4-scout-17b-16e-instruct",
    "embedder": "bge-m3",
}


def model_for(role: str) -> str:
    """Models are chosen by config, not code (rule 8). Fall back to defaults before the freeze."""
    override = os.environ.get("LLM_MODEL_" + {"llm_main": "MAIN", "llm_fast": "FAST", "llm_vision": "VISION", "embedder": "EMBEDDER"}.get(role, ""))
    if override:  # e.g. a local Ollama model name
        return override
    path = settings.models_config
    try:
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            roles = data.get("roles", data)
            if isinstance(roles, dict) and role in roles:
                value = roles[role]
                return value if isinstance(value, str) else value.get("name", DEFAULT_MODELS[role])
    except Exception:  # config problems must not take the service down
        pass
    return DEFAULT_MODELS[role]
