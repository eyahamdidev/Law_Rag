"""Report local readiness without calling an LLM or exposing credentials."""
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

def main():
    packages = {}
    for distribution, module in {
        "fastapi": "fastapi", "uvicorn": "uvicorn", "pydantic": "pydantic",
        "pymupdf": "pymupdf", "fastembed": "fastembed", "qdrant-client": "qdrant_client",
        "onnxruntime": "onnxruntime", "rank-bm25": "rank_bm25", "langgraph": "langgraph",
        "openai": "openai", "pytest": "pytest", "python-docx": "docx",
    }.items():
        importlib.import_module(module)
        packages[distribution] = importlib.metadata.version(distribution)
    from app.config import settings
    from app.modules.rag.ingestion.pipeline import load_chunks
    import onnxruntime
    result = {
        "python": sys.version.split()[0],
        "interpreter": sys.executable,
        "packages": packages,
        "onnx_providers": onnxruntime.get_available_providers(),
        "retrieval_mode": settings.retrieval_mode,
        "reranker_enabled": settings.use_reranker,
        "groq_key_present": bool(settings.groq_api_key),
        "gemini_key_present": bool(settings.gemini_api_key),
        "legal_pdfs": len(list(settings.law_corpus_dir.rglob("*.pdf"))),
        "indexed_chunks": len(load_chunks(settings.chunk_strategy)),
    }
    print(json.dumps(result, ensure_ascii=True, indent=2))

if __name__ == "__main__":
    main()
