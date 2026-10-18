"""Final institutional rewrite: the six fixed sections.

Default is one batched call (final_writer@v6, evidence-grounded and
anti-fabrication specification: internal fact table, hard rule that missing
information becomes a [NEEDED: ...] placeholder instead of an invented claim,
bottom-up market sizing only, eight-point final validation collecting the open
items plus a one-line verdict) that writes all six sections in a single reply,
so a slow model pays the context prefill once; any section the reply dropped
is topped up individually with the per-section prompt (final_writer@v2).
``mode="sequential"`` writes every section one call at a time. After every
section ``writer.guard`` marks each figure that is not traceable to the inputs
with "[to be confirmed by the founder]".

Temperature is always 0; ``seed`` selects the deterministic generation
(default SEED, changed by the regenerate option to re-roll the same inputs).

Degradation, same philosophy as the other agents: no key, a timeout, bad JSON
or an exhausted time budget turns that section into an empty text with a status
note; the function itself never raises and always returns all six ids.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from app.agents import writer
from app.config import model_for, settings
from app.llm import LLMUnavailable

SECTION_IDS = ["executive_summary", "market_opportunity", "competitive_advantage",
               "go_to_market", "operational_roadmap", "financial_strategy"]
SECTION_TITLES = {
    "executive_summary": "Executive Summary",
    "market_opportunity": "Market Opportunity & Target Segmentation",
    "competitive_advantage": "Competitive Advantage & Defended Moat",
    "go_to_market": "Go-to-Market (GTM) & Customer Acquisition",
    "operational_roadmap": "Operational Roadmap & Target Milestones",
    "financial_strategy": "Financial Strategy & Assumption Base",
}

SECTION_PROMPT_VERSION = 2  # one section per call, used for top-ups and sequential mode
BATCH_PROMPT_VERSION = 6    # all six sections in one reply, anti-fabrication spec
BATCH_MARKER = "ALL SIX"    # unique to the v3 text, used by tests to tell the two prompts apart
MAX_FACTS_CHARS = 8000
MAX_PLAN_CHARS = 12000
MAX_CRIT_CHARS = 6000
MAX_TOKENS = 1100
BATCH_MAX_TOKENS = 2400
SEED = 7  # fixed, same as app.llm, so benchmark reruns are comparable


def _remaining(deadline: float | None) -> float:
    return 1e9 if deadline is None else deadline - time.monotonic()


async def _post(client: httpx.AsyncClient, body: dict, remaining: float) -> tuple[str, dict]:
    try:
        resp = await client.post(f"{settings.llm_base_url}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                                 timeout=min(remaining, settings.llm_request_timeout_s))
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"model endpoint unreachable: {exc.__class__.__name__}") from exc
    if resp.status_code != 200:
        raise LLMUnavailable(f"model endpoint returned HTTP {resp.status_code}.")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"], data.get("usage") or {}
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable("unexpected response shape from the model endpoint.") from exc


async def _chat_section(client: httpx.AsyncClient, *, model: str, system: str, user: str,
                        schema: dict | None, deadline: float | None, max_retries: int,
                        max_tokens: int = MAX_TOKENS, seed: int = SEED) -> tuple[dict, dict]:
    """One model call. Retries 429/5xx and network errors with backoff; JSON/shape failures raise at once."""
    body: dict = {"model": model, "temperature": 0, "seed": seed, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if schema and settings.llm_json_mode == "json_schema":
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "section", "strict": False, "schema": schema}}
    else:
        body["response_format"] = {"type": "json_object"}
    delay = 1.0
    for attempt in range(max_retries + 1):
        remaining = _remaining(deadline)
        if remaining <= 1.0:
            raise LLMUnavailable("time budget exhausted before the model answered.")
        try:
            text, usage = await _post(client, body, remaining)
        except LLMUnavailable as exc:
            msg = str(exc)
            transient = (msg.startswith("model endpoint unreachable") or "HTTP 429" in msg
                         or msg.startswith("model endpoint returned HTTP 5"))
            if not transient or attempt >= max_retries:
                raise
            await _sleep(min(delay, max(_remaining(deadline) - 1, 0)))
            delay *= 2
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable("model returned text that is not JSON.") from exc
        if not isinstance(parsed, dict):
            raise LLMUnavailable("model returned JSON that is not an object.")
        return parsed, usage
    raise LLMUnavailable("model call failed.")


async def _sleep(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)


def _batch_sections(got: dict) -> dict[str, str]:
    """Id -> text for every well-formed, non-empty, known section in a batch reply (first occurrence wins)."""
    out: dict[str, str] = {}
    for item in got.get("sections") or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if sid in SECTION_IDS and sid not in out and text:
            out[sid] = text
    return out


async def run_final_writer_agent(prompts, facts: str, current_plan: str, critique_report: str, *,
                                 deadline: float | None = None, transport: httpx.AsyncBaseTransport | None = None,
                                 max_retries: int = 2, mode: str = "batch", seed: int = SEED) -> dict:
    """Write the six final sections. Batch mode: one call, then a per-section top-up for what is missing.

    ``seed`` re-rolls the deterministic generation (the regenerate option).
    The batch reply's ``open_items`` and ``verdict`` are passed through when present.
    Returns all six ids, each with a status; never raises.
    """
    if mode not in ("batch", "sequential"):
        mode = "batch"
    ps = prompts.load("final_writer", SECTION_PROMPT_VERSION)
    pb = prompts.load("final_writer", BATCH_PROMPT_VERSION)
    model = model_for("llm_main")
    marker = writer.MARKERS["en"]
    allowed = writer.allowed_numbers(facts, current_plan, critique_report)
    system = "You write the sections of an institutional business plan. Reply with JSON only."
    common = {"facts": facts[:MAX_FACTS_CHARS], "plan": current_plan[:MAX_PLAN_CHARS],
              "critique": critique_report[:MAX_CRIT_CHARS], "marker": marker}
    texts: dict[str, str] = {}
    errors: dict[str, str] = {}
    extra: dict[str, object] = {}
    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    configured = bool(settings.llm_api_key) or transport is not None
    try:
        async with httpx.AsyncClient(transport=transport) as client:
            async def call(user: str, schema: dict | None, max_tokens: int, retries: int) -> dict:
                got, u = await _chat_section(client, model=model, system=system, user=user, schema=schema,
                                             deadline=deadline, max_retries=retries, max_tokens=max_tokens,
                                             seed=seed)
                usage["calls"] += 1
                usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
                usage["completion_tokens"] += int(u.get("completion_tokens") or 0)
                return got

            if configured and mode == "batch":
                try:
                    got = await call(prompts.render(pb["text"], **common), pb.get("output_schema"),
                                     BATCH_MAX_TOKENS, max_retries)
                    texts.update(_batch_sections(got))
                    items = got.get("open_items")
                    if isinstance(items, list) and items:
                        extra["open_items"] = [str(i).strip() for i in items if str(i).strip()]
                    verdict = got.get("verdict")
                    if isinstance(verdict, str) and verdict.strip():
                        extra["verdict"] = verdict.strip()
                except Exception as exc:  # noqa: BLE001  the per-section round below recovers what it can
                    errors["batch"] = f"{exc.__class__.__name__}: {exc}"[:200]
            if configured:
                for sid in SECTION_IDS:
                    if sid in texts:
                        continue
                    if _remaining(deadline) <= 1.0:
                        errors[sid] = "LLMUnavailable: time budget exhausted before the model answered."
                        continue
                    try:
                        got = await call(prompts.render(ps["text"], section=SECTION_TITLES[sid], **common),
                                         ps.get("output_schema"), MAX_TOKENS, 0 if "batch" in errors else max_retries)
                        rid = str(got.get("id") or "").strip()
                        if rid and rid != sid:
                            raise ValueError(f"model wrote section '{rid}' instead of '{sid}'.")
                        text = str(got.get("text", "")).strip()
                        if not text:
                            raise ValueError("model returned an empty section.")
                        texts[sid] = text
                    except Exception as exc:  # noqa: BLE001  one broken section must not lose the other five
                        errors[sid] = f"{exc.__class__.__name__}: {exc}"[:200]
    except Exception as exc:  # noqa: BLE001  the whole step degrades, never crashes the pipeline
        errors["fatal"] = f"{exc.__class__.__name__}: {exc}"[:200]
    sections = []
    for sid in SECTION_IDS:
        entry = {"id": sid, "title": SECTION_TITLES[sid], "text": "", "flagged": [], "status": "ok"}
        if sid in texts:
            entry["text"], entry["flagged"] = writer.guard(texts[sid], allowed, "en")
        else:
            entry["status"] = "skipped" if not configured else "error"
            entry["error"] = ("no language model key configured" if not configured
                              else errors.get(sid) or errors.get("batch") or errors.get("fatal")
                              or "section missing from the model reply.")
        sections.append(entry)
    ok = sum(1 for s in sections if s["status"] == "ok")
    result = {"method": "model" if ok == len(SECTION_IDS) else ("partial" if ok else "unavailable"),
              "mode": mode, "model": model, "prompt_id": prompts.ref(pb if mode == "batch" else ps),
              "sections": sections, "usage": usage}
    result.update(extra)
    return result
