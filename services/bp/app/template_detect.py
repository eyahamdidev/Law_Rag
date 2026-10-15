"""Detect a plan that is still a blank or sample-filled template.

A template carries help tips, 'Start writing here' prompts, placeholder names (John Doe, [YEAR], [Company Name],
example.com). Its help text can satisfy a keyword rubric without any founder content, so such a file must not
be scored like a plan. The check is deliberately conservative: it needs several distinct kinds of evidence.
"""
from __future__ import annotations

import re

PATTERNS = {
    "start_writing": re.compile(r"start writing here|commencez à rédiger|write a call to action|écrivez ici", re.I),
    "help_tip": re.compile(r"\bhelp tip\b|to unlock help|conseil d'aide|astuce\b.{0,20}remplir", re.I),
    "year_token": re.compile(r"\[\s*(?:year|année|date|xx+|insert [^\]]{1,30})\s*\]", re.I),
    "name_token": re.compile(r"\[\s*(?:company|business|your|nom|name|type|field|list|he/she|university|institution)[^\]]{0,50}\]", re.I),
    "lorem": re.compile(r"lorem ipsum", re.I),
    "dummy_person": re.compile(r"\bjohn doe\b|\bjane doe\b|@example\.(?:com|org)|\bwww\.example\.com\b", re.I),
    "vendor_ad": re.compile(r"create your business plan today|try upmetrics|join over \d+k entrepreneurs", re.I),
}


def scan(text: str) -> dict:
    kinds: dict[str, int] = {}
    examples: list[str] = []
    for kind, pat in PATTERNS.items():
        hits = pat.findall(text) if pat.groups == 0 else [m.group(0) for m in pat.finditer(text)]
        hits = [h if isinstance(h, str) else str(h) for h in hits]
        if hits:
            kinds[kind] = len(hits)
            examples.append(hits[0][:40])
    total = sum(kinds.values())
    unfilled = (len(kinds) >= 3 and total >= 8) or kinds.get("start_writing", 0) >= 4 or kinds.get("lorem", 0) >= 2
    return {"unfilled": unfilled, "total": total, "kinds": kinds, "examples": examples[:4]}
