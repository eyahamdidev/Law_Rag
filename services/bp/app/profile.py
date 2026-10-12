"""Merge what we know about the founder from three sources.

Sources, strongest first:
1. ``questionnaire``  the founder answered this module's own questions.
2. ``orchestrator``   the gateway collected it elsewhere (chat, aid tab, intake).
3. ``document``       a fact read out of the uploaded plan.

A stronger source wins. A disagreement is never silent: it is recorded as a
conflict so the report can say "review this" instead of picking quietly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.questionnaire import BANK_BY_ID, REQUIRED_IDS, Cleaned, clean_answers, clean_profile

PRECEDENCE = ("questionnaire", "orchestrator", "document")


@dataclass
class Context:
    values: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    conflicts: list[dict] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    ignored_keys: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        scale = max(abs(a), abs(b), 1.0)
        return abs(a - b) <= 0.01 * scale
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    return a == b


def merge_context(
    profile: dict[str, Any] | None,
    answers: dict[str, Any] | None,
    doc_facts: dict[str, Any] | None = None,
) -> Context:
    layers: dict[str, Cleaned] = {
        "questionnaire": clean_answers(answers),
        "orchestrator": clean_profile(profile),
        "document": clean_answers(doc_facts),  # doc facts use the same ids; bad ones are dropped
    }
    ctx = Context()
    for name in PRECEDENCE:
        layer = layers[name]
        if layer.values:
            ctx.sources_used.append(name)
        if name == "questionnaire":
            ctx.errors.update(layer.errors)
            ctx.ignored_keys.extend(layer.unknown)
        for key, value in layer.values.items():
            if key not in ctx.values:
                ctx.values[key] = value
                ctx.provenance[key] = name
                continue
            if BANK_BY_ID[key].type in ("year_series", "items", "longtext"):
                continue  # free text and series differ naturally; the checker compares numbers
            if not _same(ctx.values[key], value):
                existing = next((c for c in ctx.conflicts if c["field"] == key), None)
                if existing is None:
                    existing = {"field": key, "chosen_source": ctx.provenance[key], "values": {ctx.provenance[key]: ctx.values[key]}}
                    ctx.conflicts.append(existing)
                existing["values"][name] = value
    return ctx


def missing_required(ctx: Context, extra_present: set[str] | None = None) -> list[str]:
    present = set(ctx.values) | (extra_present or set())
    return [qid for qid in REQUIRED_IDS if qid not in present]
