"""Mask personal and fiscal identifiers before any text leaves the machine (spec 2.4).

Names, fiscal ids, RIB/IBAN, e-mails and phone numbers are replaced by stable
placeholders such as ``[[FISCAL_1]]``. The mapping stays in memory. After the
model answers, ``unmask`` puts the real values back. The report lists how many
items of each kind were masked, never the values.

The fiscal-identifier pattern is permissive on purpose. The exact official
format is confirmed by the team (spec section 4); this module only needs to
catch candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("IBAN", re.compile(r"\bTN\s?\d{2}(?:\s?\d{4}){5}\b", re.I)),
    ("RIB", re.compile(r"\b\d{2}\s?\d{3}\s?\d{13}\s?\d{2}\b")),
    ("FISCAL", re.compile(r"\b\d{6,7}\s?[/\-]?\s?[A-Z]\s?[/\-]?\s?[AMPNC]\s?[/\-]?\s?\d{3}\b")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("PHONE", re.compile(r"(?:\+216[\s.-]?)?\b\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b")),
]


@dataclass
class Masker:
    names: list[str] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    _reverse: dict[str, str] = field(default_factory=dict)

    def _token(self, kind: str, value: str) -> str:
        if value in self._reverse:
            return self._reverse[value]
        self.counts[kind] = self.counts.get(kind, 0) + 1
        token = f"[[{kind}_{self.counts[kind]}]]"
        self.mapping[token] = value
        self._reverse[value] = token
        return token

    def mask(self, text: str) -> str:
        if not text:
            return text
        for name in sorted({n.strip() for n in self.names if n and len(n.strip()) >= 3}, key=len, reverse=True):
            text = re.sub(re.escape(name), lambda m: self._token("NAME", m.group(0)), text, flags=re.I)
        for kind, pat in PATTERNS:
            text = pat.sub(lambda m, k=kind: self._token(k, m.group(0)), text)
        return text

    def unmask(self, text: str) -> str:
        for token, value in self.mapping.items():
            text = text.replace(token, value)
        return text

    def unmask_obj(self, obj):
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, list):
            return [self.unmask_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.unmask_obj(v) for k, v in obj.items()}
        return obj

    def report(self) -> dict[str, int]:
        return dict(self.counts)


class NoMasker(Masker):
    def mask(self, text: str) -> str:  # masking switched off by the caller, stated in the report
        return text
