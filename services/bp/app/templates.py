"""Template skeletons (BFPME creation/extension, GIZ) loaded from templates/*.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import SERVICE_ROOT
from app.contract import ModuleError

TEMPLATE_DIR = SERVICE_ROOT / "templates"
TEMPLATE_IDS = ("bfpme_creation", "bfpme_extension", "giz", "investor_pitch")


@lru_cache(maxsize=8)
def load_template(template_id: str) -> dict:
    if template_id not in TEMPLATE_IDS:
        raise ModuleError("BAD_INPUT", f"Unknown template '{template_id}'. Use one of {', '.join(TEMPLATE_IDS)}.")
    path: Path = TEMPLATE_DIR / f"{template_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


PITCH_HEADS = ("executive summary", "problem", "market", "business model", "financials", "funding ask", "team", "risks",
               "traction", "solution")


def looks_like_pitch(headings: list[str]) -> bool:
    """True when the document headings follow the short investor-pitch layout."""
    folded = [h.lower() for h in headings]
    hits = sum(any(h.startswith(p) for h in folded) for p in PITCH_HEADS)
    return hits >= 4


def choose_template(requested: str | None, stage: str | None, headings: list[str] | None = None) -> str:
    """Explicit choice wins. Then the document's own headings. Then the company stage."""
    if requested:
        return requested
    if headings and looks_like_pitch(headings):
        return "investor_pitch"
    if stage in ("extension", "growth"):
        return "bfpme_extension"
    return "bfpme_creation"


def section_index(template: dict) -> dict[str, dict]:
    return {s["id"]: s for s in template["sections"]}


def label(obj: dict, lang: str) -> str:
    return obj.get(lang) or obj.get("en") or next(iter(obj.values()), "")
