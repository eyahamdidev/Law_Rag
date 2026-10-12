"""Chat, JSON and vision calls to free hosted models.

Groq is the primary provider: free tier, OpenAI-compatible, and fast enough
that a plan -> 2 agents -> verify -> compose turn stays well under a minute.
Gemini is the fallback when Groq rate-limits or fails, and the vision model
for OCR of scanned pages and uploaded documents. Both are reached through
their OpenAI-compatible endpoints, so one client covers both.

Three tiers per provider:
  main     answer drafting                         (Groq gpt-oss-120b)
  fast     planner and claim verifier              (Groq qwen3.8-27b)
  compose  merging several agents' answers         (Groq gpt-oss-20b)

Groq's free tier allows 8,000 tokens per minute and 1,000 requests per day
*per model*, so spreading the calls of one turn across three models triples
the budget for a turn (measured: one model alone hit 429 on a two-agent turn).

gpt-oss models reason before answering, and those hidden tokens count toward
max_tokens: measured at the default effort, 298 of 300 tokens went to reasoning
and the visible answer was empty. They are called with reasoning_effort=low
(7 reasoning tokens for the same request), and a reply cut by the token limit
is retried once with twice the limit.

Without any API key, calls raise LLMUnavailable. Callers catch it and fall
back (keyword router, extractive answer) so the app still runs offline.
"""

import base64
import json
import re
import time
from dataclasses import dataclass

from app.config import settings

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key": lambda: settings.groq_api_key,
        "main": lambda: settings.groq_model,
        "fast": lambda: settings.groq_fast_model,
        "compose": lambda: settings.groq_compose_model,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key": lambda: settings.gemini_api_key,
        "main": lambda: settings.gemini_model,
        "fast": lambda: settings.gemini_fast_model,
        "compose": lambda: settings.gemini_model,
    },
}


# Rate limited, or the provider is overloaded ("high demand"): worth one retry.
RETRYABLE = {429, 500, 502, 503}


def _retry_delay(error: Exception, default: float = 2.0, cap: float = 8.0) -> float:
    """Honour the provider's retry-after header, but never block a turn for long."""
    response = getattr(error, "response", None)
    try:
        return min(float(response.headers.get("retry-after", default)), cap)
    except (AttributeError, TypeError, ValueError):
        return default


class LLMUnavailable(RuntimeError):
    """No provider is configured, or every configured provider failed."""


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def json(self) -> dict:
        return parse_json(self.text)


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating code fences and leading prose."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


class LLMClient:
    def __init__(self) -> None:
        self._clients: dict[str, object] = {}

    def configured(self) -> list[str]:
        order = [settings.llm_provider, settings.llm_fallback_provider]
        seen = []
        for name in order:
            if name in PROVIDERS and name not in seen and PROVIDERS[name]["key"]():
                seen.append(name)
        return seen

    @property
    def available(self) -> bool:
        return bool(self.configured())

    def _client(self, provider: str):
        if provider not in self._clients:
            from openai import OpenAI

            spec = PROVIDERS[provider]
            self._clients[provider] = OpenAI(
                api_key=spec["key"](),
                base_url=spec["base_url"],
                timeout=settings.llm_timeout_s,
                max_retries=0,  # retries and fallback are handled here
            )
        return self._clients[provider]

    def chat(
        self,
        messages: list[dict],
        *,
        tier: str = "main",
        json_mode: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> LLMResult:
        providers = self.configured()
        if not providers:
            raise LLMUnavailable("Set GROQ_API_KEY or GEMINI_API_KEY in .env.")
        errors = []
        for provider in providers:
            model = PROVIDERS[provider][tier]()
            for attempt in range(2):
                started = time.perf_counter()
                try:
                    kwargs = {}
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    if "gpt-oss" in model:
                        kwargs["extra_body"] = {"reasoning_effort": settings.llm_reasoning_effort}
                    response = self._client(provider).chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    )
                    if response.choices[0].finish_reason == "length" and attempt == 0:
                        errors.append(f"{provider}/{model}: cut at {max_tokens} tokens, retrying with {max_tokens * 2}")
                        max_tokens *= 2
                        continue
                    usage = getattr(response, "usage", None)
                    return LLMResult(
                        text=response.choices[0].message.content or "",
                        provider=provider,
                        model=model,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        prompt_tokens=getattr(usage, "prompt_tokens", None),
                        completion_tokens=getattr(usage, "completion_tokens", None),
                    )
                except Exception as error:  # rate limit, timeout, provider outage
                    errors.append(f"{provider}/{model}: {type(error).__name__}: {str(error)[:160]}")
                    status = getattr(error, "status_code", None)
                    if status in RETRYABLE and attempt == 0:
                        time.sleep(_retry_delay(error))
                        continue
                    break
        raise LLMUnavailable("; ".join(errors))

    def chat_json(self, messages: list[dict], **kwargs) -> tuple[dict, LLMResult]:
        """JSON-mode call with one repair attempt when the output does not parse."""
        result = self.chat(messages, json_mode=True, **kwargs)
        try:
            return result.json(), result
        except (json.JSONDecodeError, ValueError):
            repair = messages + [
                {"role": "assistant", "content": result.text},
                {"role": "user", "content": "That was not valid JSON. Reply with the JSON object only."},
            ]
            result = self.chat(repair, json_mode=True, **kwargs)
            return result.json(), result

    def vision(self, image_bytes: bytes, prompt: str, mime: str = "image/png") -> LLMResult:
        """Read an image (scanned page, photo of a canvas, receipt). Gemini only:
        Groq no longer serves a vision model on its free tier."""
        providers = ["gemini"] if PROVIDERS["gemini"]["key"]() else []
        if not providers:
            raise LLMUnavailable("Vision needs GEMINI_API_KEY.")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        message = {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ],
        }
        errors = []
        # Both Gemini tiers read images; the lighter one is the fallback when the main one is overloaded.
        for model in dict.fromkeys([settings.gemini_model, settings.gemini_fast_model]):
            for attempt in range(2):
                started = time.perf_counter()
                try:
                    response = self._client("gemini").chat.completions.create(
                        model=model, messages=[message], temperature=0.0, max_tokens=4000
                    )
                    return LLMResult(
                        text=response.choices[0].message.content or "",
                        provider="gemini",
                        model=model,
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                except Exception as error:
                    errors.append(f"gemini/{model}: {type(error).__name__}: {str(error)[:160]}")
                    if getattr(error, "status_code", None) in RETRYABLE and attempt == 0:
                        time.sleep(3.0)
                        continue
                    break
        raise LLMUnavailable("; ".join(errors))


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
