"""Load guidance/good_practice.json into the shared Qdrant (collection bp__guidance).

Needs Qdrant and the local Ollama (bge-m3) running:  python scripts/ingest_guidance.py
The service works without this step; it falls back to lexical ranking.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agents.guidance import ingest  # noqa: E402

if __name__ == "__main__":
    print("points written:", ingest())
