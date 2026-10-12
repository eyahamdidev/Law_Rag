"""Template guidance retrieval for the writer.

Order of attempts:
1. Qdrant collection ``bp__guidance`` with bge-m3 embeddings from the local Ollama.
2. A small in-process lexical ranker over ``guidance/good_practice.json``.

The service must work with neither Qdrant nor Ollama running, so every network
step has a short timeout and falls through to the lexical ranker.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache

import httpx

from app.agents.common import fold
from app.config import SERVICE_ROOT, model_for, settings

COLLECTION = "bp__guidance"
PATH = SERVICE_ROOT / "guidance" / "good_practice.json"


@lru_cache(maxsize=1)
def passages() -> list[dict]:
    return json.loads(PATH.read_text(encoding="utf-8"))["passages"]


def _tok(text: str) -> list[str]:
    return re.findall(r"\w{3,}", fold(text))


def _lexical(section_id: str, query: str, k: int) -> list[dict]:
    pool = [p for p in passages() if p["section_id"] == section_id] or passages()
    docs = [Counter(_tok(p["title"] + " " + p["text"])) for p in pool]
    df = Counter(t for d in docs for t in d)
    q = _tok(query) + _tok(section_id.replace("_", " "))
    scored = []
    for p, d in zip(pool, docs):
        s = sum((1 + math.log(d[t])) * math.log(1 + len(pool) / df[t]) for t in set(q) if t in d)
        s += 5.0 if p["section_id"] == section_id else 0.0
        scored.append((s, p))
    scored.sort(key=lambda x: -x[0])
    return [{**p, "score": round(s, 3), "score_kind": "relevance"} for s, p in scored[:k]]


def _embed(text: str) -> list[float] | None:
    try:
        r = httpx.post(f"{settings.ollama_url}/api/embeddings", json={"model": model_for("embedder"), "prompt": text}, timeout=3.0)
        r.raise_for_status()
        return r.json()["embedding"]
    except Exception:  # noqa: BLE001
        return None


def retrieve(section_id: str, query: str, k: int = 2) -> list[dict]:
    if settings.use_vector_store:
        vec = _embed(query or section_id)
        if vec:
            try:
                r = httpx.post(
                    f"{settings.qdrant_url}/collections/{COLLECTION}/points/search",
                    json={"vector": vec, "limit": k, "with_payload": True,
                          "filter": {"must": [{"key": "section_id", "match": {"value": section_id}}]}},
                    timeout=3.0,
                )
                r.raise_for_status()
                hits = r.json().get("result", [])
                if hits:
                    return [{**h["payload"], "score": round(float(h["score"]), 3), "score_kind": "relevance"} for h in hits]
            except Exception:  # noqa: BLE001
                pass
    return _lexical(section_id, query, k)


def ingest() -> int:
    """Create bp__guidance and upload the passages. Run once: python scripts/ingest_guidance.py"""
    items = passages()
    first = _embed(items[0]["text"])
    if not first:
        raise RuntimeError("Embedder is not reachable. Start the local Ollama with bge-m3.")
    base = settings.qdrant_url
    httpx.put(f"{base}/collections/{COLLECTION}", json={"vectors": {"size": len(first), "distance": "Cosine"}}, timeout=10).raise_for_status()
    points = []
    for n, p in enumerate(items, start=1):
        vec = _embed(p["title"] + ". " + p["text"])
        points.append({"id": n, "vector": vec, "payload": p})
    httpx.put(f"{base}/collections/{COLLECTION}/points?wait=true", json={"points": points}, timeout=30).raise_for_status()
    return len(points)
