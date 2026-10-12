"""Small helpers shared by the agents: text normalisation and the trace recorder."""

from __future__ import annotations

import re
import time
import unicodedata
from contextlib import contextmanager

from app.contract import TraceStep

_AR_DIAC = re.compile(r"[ً-ٰٟ]")


def norm(text: str) -> str:
    """Lowercase, unify apostrophes, strip Arabic diacritics. Keeps French accents (keywords include them)."""
    t = unicodedata.normalize("NFC", text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace(" ", " ")
    return _AR_DIAC.sub("", t)


def fold(text: str) -> str:
    """Accent-insensitive form used when matching free text."""
    return "".join(c for c in unicodedata.normalize("NFD", norm(text)) if unicodedata.category(c) != "Mn")


class Trace:
    """Collects one TraceStep per pipeline step with its duration."""

    def __init__(self) -> None:
        self.steps: list[TraceStep] = []
        self.notes: list[str] = []

    @contextmanager
    def step(self, name: str, model: str | None = None, prompt_id: str | None = None):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.steps.append(TraceStep(step=name, ms=int((time.perf_counter() - t0) * 1000), model=model, prompt_id=prompt_id))

    def note(self, text: str) -> None:
        self.notes.append(text)
