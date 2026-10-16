"""What the orchestrator learns about the founder while they use the site.

The profile is kept per browser session (header ``X-Session-Id``), in memory.
Chat messages and the aid form feed it. The business-plan module receives it as
``profile`` next to the answers the founder gives in the BP questionnaire. The
BP module decides precedence (questionnaire first) and reports conflicts.

Hints from free text are cautious: a pattern that is not clear is not stored.
"""

from __future__ import annotations

import re
import threading
import time

_TTL_S = 6 * 3600
_LOCK = threading.Lock()
_STORE: dict[str, tuple[float, dict]] = {}

_LEGAL = re.compile(r"\b(SUARL|SARL|SAS)\b")
_STAGE = [
    (re.compile(r"\b(extension|étendre|etendre|agrandir|expansion|développer mon entreprise)\b", re.I), "extension"),
    (re.compile(r"\b(création|creation|créer|creer|lancer|démarrer|demarrer|idée|idee|startup)\b", re.I), "creation"),
]
_HEADCOUNT = re.compile(r"\b(\d{1,3})\s+(salariés|salaries|employés|employes|employees|personnes)\b", re.I)
_AMOUNT = re.compile(r"\b(\d{1,3}(?:[ . ]\d{3})+|\d{4,9})\s*(dt|tnd|dinars?)\b", re.I)
_SECTOR = re.compile(r"\b(?:secteur|sector|activité|activity)\s*(?:de|d'|du|:)?\s*([A-Za-zÀ-ÿ' -]{3,40})", re.I)
_FUNDING_WORDS = re.compile(r"financ|crédit|credit|prêt|pret|loan|besoin|need|emprunt", re.I)


def hints_from_text(text: str) -> dict:
    out: dict = {}
    if m := _LEGAL.search(text):
        out["legal_form"] = m.group(1)
    for pat, stage in _STAGE:
        if pat.search(text):
            out["stage"] = stage
            break
    if m := _HEADCOUNT.search(text):
        out["headcount"] = int(m.group(1))
    if (m := _AMOUNT.search(text)) and _FUNDING_WORDS.search(text):
        out["funding_amount"] = int(re.sub(r"[ . ]", "", m.group(1)))
    if m := _SECTOR.search(text):
        out["sector"] = m.group(1).strip(" .,-")
    return out


def _gc() -> None:
    now = time.time()
    for k in [k for k, (t, _) in _STORE.items() if now - t > _TTL_S]:
        _STORE.pop(k, None)


def get(session_id: str | None) -> dict:
    if not session_id:
        return {}
    with _LOCK:
        _gc()
        return dict(_STORE.get(session_id, (0, {}))[1])


def merge(session_id: str | None, partial: dict, source: str = "orchestrator") -> dict:
    """Newer values replace older ones. Empty values never erase what is known."""
    if not session_id or not partial:
        return get(session_id)
    clean = {k: v for k, v in partial.items() if v not in (None, "", "unspecified")}
    with _LOCK:
        _gc()
        cur = dict(_STORE.get(session_id, (0, {}))[1])
        cur.update(clean)
        _STORE[session_id] = (time.time(), cur)
        return dict(cur)


def clear(session_id: str | None) -> None:
    with _LOCK:
        _STORE.pop(session_id or "", None)
