from __future__ import annotations

from difflib import SequenceMatcher

from fraud_detection.normalize import normalize_name, strip_legal_suffix
from fraud_detection.schema import SanctionsEntry


class SanctionsIndex:
    """Normalized name match against loaded sanctions entries.

    Exact and legal-suffix matches score 1. Fuzzy matching runs only for names
    that contain a space and are at least 8 characters, share the first token
    with the candidate, and reach a SequenceMatcher ratio of 0.92. At most 200
    same-token candidates are compared.
    """

    def __init__(self, entries: list[SanctionsEntry]):
        self.entries = list(entries)
        self.available = bool(self.entries)
        self._exact: dict[str, SanctionsEntry] = {}
        self._by_first: dict[str, list[tuple[str, SanctionsEntry]]] = {}
        for entry in self.entries:
            self._index(entry)

    def _index(self, entry: SanctionsEntry) -> None:
        normalized = normalize_name(entry.name)
        if not normalized:
            return
        self._exact.setdefault(normalized, entry)
        stripped = strip_legal_suffix(normalized)
        if stripped:
            self._exact.setdefault(stripped, entry)
        first = normalized.split()[0]
        bucket = self._by_first.setdefault(first, [])
        if len(bucket) < 200:
            bucket.append((normalized, entry))

    def match(self, name: str) -> SanctionsEntry | None:
        found = self.match_scored(name)
        if found is None:
            return None
        return found[0]

    def match_scored(self, name: str, *, possible: bool = False) -> tuple[SanctionsEntry, float] | None:
        if not self.available or not name or not str(name).strip():
            return None
        normalized = normalize_name(name)
        if not normalized:
            return None
        exact = self._exact.get(normalized)
        if exact is not None:
            return exact, 1.0
        stripped = strip_legal_suffix(normalized)
        if stripped:
            exact = self._exact.get(stripped)
            if exact is not None:
                return exact, 1.0
        if len(normalized) < 8 or " " not in normalized:
            return None
        first = normalized.split()[0]
        best_entry = None
        best_score = 0.0
        for candidate, entry in self._by_first.get(first, ()):
            score = SequenceMatcher(None, normalized, candidate).ratio()
            if score > best_score:
                best_score = score
                best_entry = entry
        cutoff = 0.85 if possible else 0.92
        if best_entry is not None and best_score >= cutoff:
            return best_entry, float(best_score)
        return None
