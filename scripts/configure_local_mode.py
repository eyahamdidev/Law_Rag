"""Configure key-free local execution without printing or replacing API keys."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    path = ROOT / ".env"
    content = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    changes = {"LOCAL_LLM_ENABLED": "true", "LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
               "LOCAL_LLM_MODEL": "local-legal", "EMBEDDING_MODEL": "local/multilingual-e5-small-int8",
               "USE_RERANKER": "false", "EMBEDDING_DEVICE": "cpu", "LEGAL_WEB_FALLBACK_ENABLED":"true"}
    rows = [line for line in content.splitlines() if line.partition("=")[0] not in changes]
    rows.extend(f"{key}={value}" for key, value in changes.items())
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("Local-model fallback and CPU multilingual embeddings configured. API keys were preserved.")
