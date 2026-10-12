"""OpenAI-compatible chat client over plain httpx (rule 5).

* Base URL and key come from the environment. Groq by default, a local Ollama
  ``/v1`` endpoint works with the same code.
* Temperature 0 and a fixed seed.
* Retries on 429 and 5xx with exponential backoff, honouring Retry-After.
* Responses are cached in SQLite by a hash of model, messages and parameters,
  so a benchmark rerun does not spend tokens twice.
* Everything that can fail raises ``LLMUnavailable``. Callers degrade to the
  deterministic path. The service never crashes because a model is down.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import settings


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    rate_limited: int = 0
    models: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {"calls": self.calls, "cache_hits": self.cache_hits, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens, "http_429": self.rate_limited, "models": sorted(self.models)}


class _Cache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._ok = True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")
        except Exception:
            self._ok = False

    def get(self, key: str) -> str | None:
        if not self._ok:
            return None
        try:
            with sqlite3.connect(self.path) as db:
                row = db.execute("SELECT v FROM c WHERE k=?", (key,)).fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def put(self, key: str, value: str) -> None:
        if not self._ok:
            return
        try:
            with sqlite3.connect(self.path) as db:
                db.execute("INSERT OR REPLACE INTO c VALUES (?,?)", (key, value))
        except Exception:
            pass


class LLMClient:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None,
                 transport: httpx.BaseTransport | None = None, deadline: float | None = None,
                 max_retries: int = 3, cache: bool = True) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.transport = transport
        self.deadline = deadline  # absolute time.monotonic() value
        self.max_retries = max_retries
        self.usage = Usage()
        self._cache = _Cache(settings.llm_cache_path) if cache else None

    @property
    def available(self) -> bool:
        import os
        off = os.environ.get("BP_LLM", "auto").lower() == "off"
        return self.transport is not None or (bool(self.api_key) and not off)

    def _remaining(self) -> float:
        return 1e9 if self.deadline is None else self.deadline - time.monotonic()

    def chat_json(self, *, model: str, system: str, user: str, schema: dict | None = None,
                  images: list[str] | None = None, max_tokens: int = 2048) -> dict:
        """Return a parsed JSON object. Raises LLMUnavailable on any failure."""
        if not self.available:
            raise LLMUnavailable("No LLM key configured.")
        content: Any = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b}"}} for b in images
            ]
        body: dict[str, Any] = {
            "model": model, "temperature": 0, "seed": 7, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        }
        if schema and settings.llm_json_mode == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "strict": False, "schema": schema}}
        else:
            body["response_format"] = {"type": "json_object"}
        key = hashlib.sha256(json.dumps({"u": self.base_url, **body}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if self._cache:
            hit = self._cache.get(key)
            if hit:
                self.usage.cache_hits += 1
                self.usage.models.add(model)
                return json.loads(hit)
        text = self._post(body)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable("Model returned text that is not JSON.") from exc
        if not isinstance(parsed, dict):
            raise LLMUnavailable("Model returned JSON that is not an object.")
        if self._cache:
            self._cache.put(key, text)
        return parsed

    def _post(self, body: dict) -> str:
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            remaining = self._remaining()
            if remaining <= 1.0:
                raise LLMUnavailable("Time budget exhausted before the model answered.")
            try:
                with httpx.Client(transport=self.transport, timeout=min(remaining, 45.0)) as client:
                    resp = client.post(f"{self.base_url}/chat/completions", json=body,
                                       headers={"Authorization": f"Bearer {self.api_key}"})
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise LLMUnavailable(f"Model endpoint unreachable: {exc.__class__.__name__}") from exc
                time.sleep(min(delay, max(self._remaining() - 1, 0)))
                delay *= 2
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if resp.status_code == 429:
                    self.usage.rate_limited += 1
                if attempt >= self.max_retries:
                    raise LLMUnavailable(f"Model endpoint returned HTTP {resp.status_code}.")
                wait = delay
                try:
                    wait = max(wait, float(resp.headers.get("Retry-After", 0)))
                except ValueError:
                    pass
                time.sleep(min(wait, max(self._remaining() - 1, 0)))
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise LLMUnavailable(f"Model endpoint returned HTTP {resp.status_code}.")
            data = resp.json()
            self.usage.calls += 1
            self.usage.models.add(body["model"])
            u = data.get("usage") or {}
            self.usage.prompt_tokens += int(u.get("prompt_tokens") or 0)
            self.usage.completion_tokens += int(u.get("completion_tokens") or 0)
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMUnavailable("Unexpected response shape from the model endpoint.") from exc
        raise LLMUnavailable("Model call failed.")
