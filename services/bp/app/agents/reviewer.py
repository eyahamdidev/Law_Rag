"""Section reviewer: score each template section against its rubric and quote evidence.

* Deterministic baseline: keyword rubric. Always available.
* Model path (one batched call): rubric verdict per criterion plus a verbatim
  quote. A quote that cannot be found in the section text is discarded and the
  criterion counts as not met, so the report never shows evidence that is not
  in the plan.
* The numeric score is always computed from criteria verdicts here, never
  taken from the model.

``style`` selects the prompt variant for the benchmark: ``plain`` or ``cot``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app import prompts
from app.agents.common import Trace, fold
from app.config import model_for
from app.llm import LLMClient, LLMUnavailable
from app.masking import Masker
from app.templates import label

COMPLETE, WEAK = 70, 35
MAX_CHARS = 1800


@dataclass
class CriterionResult:
    id: str
    text: str
    met: bool
    evidence: str | None = None
    note: str | None = None


@dataclass
class SectionReview:
    section_id: str
    title: str
    required: bool
    weight: float
    status: str  # complete | weak | missing
    score: int
    criteria: list[CriterionResult] = field(default_factory=list)
    critique: str = ""
    method: str = "rules"
    text_len: int = 0
    sources: list[str] = field(default_factory=list)
    page: int | None = None
    bbox: list[float] | None = None

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["criteria"] = [c.__dict__ for c in self.criteria]
        return d


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?؟])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _score(criteria: list[CriterionResult], text: str) -> int:
    if not text.strip() or not criteria:
        return 0
    met = sum(1 for c in criteria if c.met) / len(criteria)
    return int(round(85 * met + 15 * min(1.0, len(text) / 600.0)))


def status_for(score: int, text: str) -> str:
    if not text.strip() or score < WEAK:
        return "missing" if not text.strip() or score == 0 else "weak"
    return "complete" if score >= COMPLETE else "weak"


def review_rules(sec: dict, text: str, lang: str) -> list[CriterionResult]:
    out: list[CriterionResult] = []
    sents = _sentences(text)
    folded = [fold(s) for s in sents]
    for c in sec["criteria"]:
        kws = [fold(k) for lg in ("fr", "en", "ar") for k in c["keywords"].get(lg, [])]
        quote = None
        for s, f in zip(sents, folded):
            if any(k and k in f for k in kws):
                if c.get("needs_number") and not re.search(r"\d", s):
                    continue
                quote = s[:240]
                break
        note = None
        if quote is None and c.get("needs_number") and any(any(k in f for k in kws) for f in folded):
            note = "mentioned without a figure"
        out.append(CriterionResult(c["id"], label(c["text"], lang), quote is not None, quote, note))
    return out


def _quote_ok(quote: str | None, text: str) -> bool:
    if not quote:
        return False
    q = re.sub(r"\s+", " ", fold(quote)).strip(" .…")
    t = re.sub(r"\s+", " ", fold(text))
    return len(q) >= 6 and q in t


def review_all(
    template: dict,
    sections: dict[str, dict],
    *,
    lang: str,
    llm: LLMClient,
    masker: Masker,
    trace: Trace,
    style: str = "plain",
    use_llm: bool = True,
) -> list[SectionReview]:
    reviews: list[SectionReview] = []
    for sec in template["sections"]:
        entry = sections.get(sec["id"], {})
        text = entry.get("text", "")
        crit = review_rules(sec, text, lang)
        score = _score(crit, text)
        seg = (entry.get("segments") or [{}])[0]
        reviews.append(SectionReview(
            section_id=sec["id"], title=label(sec["title"], lang), required=sec["required"], weight=sec["weight"],
            status=status_for(score, text), score=score, criteria=crit, method="rules", text_len=len(text),
            sources=entry.get("sources", []), page=seg.get("page"), bbox=seg.get("bbox"),
        ))
    if use_llm and llm.available:
        _apply_llm(template, sections, reviews, lang=lang, llm=llm, masker=masker, trace=trace, style=style)
    return reviews


def _apply_llm(template, sections, reviews, *, lang, llm, masker, trace, style):
    # v3 (investor persona, weakness-plus-fix critique) is the default; v2 stays for the cot benchmark variant.
    p = prompts.load("reviewer", 2 if style == "cot" else 3)
    items = []
    for sec, rv in zip(template["sections"], reviews):
        if rv.text_len == 0:
            continue
        items.append({
            "section_id": sec["id"],
            "title": sec["title"]["en"],
            "criteria": [{"id": c["id"], "text": c["text"]["en"], "needs_number": bool(c.get("needs_number"))} for c in sec["criteria"]],
            "text": masker.mask(sections[sec["id"]]["text"])[:MAX_CHARS],
        })
    if not items:
        return
    model = model_for("llm_main")
    user = prompts.render(p["text"], sections=json.dumps(items, ensure_ascii=False), lang=lang)
    with trace.step("reviewer.llm", model=model, prompt_id=prompts.ref(p)):
        try:
            out = llm.chat_json(model=model, system="You are a brutally honest angel investor and McKinsey-style auditor reviewing a business plan. Reply with JSON only.", user=user,
                                schema=p.get("output_schema"), max_tokens=4000)
        except LLMUnavailable as exc:
            trace.note(f"reviewer.llm skipped: {exc}")
            return
    by_id = {r["section_id"]: r for r in out.get("sections", []) if isinstance(r, dict) and "section_id" in r}
    for sec, rv in zip(template["sections"], reviews):
        res = by_id.get(sec["id"])
        if not res:
            continue
        text = sections[sec["id"]]["text"]
        verdicts = {c.get("id"): c for c in res.get("criteria", []) if isinstance(c, dict)}
        old_crit, old_score, old_status = rv.criteria, rv.score, rv.status
        new: list[CriterionResult] = []
        for c in sec["criteria"]:
            v = verdicts.get(c["id"], {})
            quote = masker.unmask(v.get("evidence_quote") or "") or None
            met = bool(v.get("met")) and _quote_ok(quote, text)
            note = None
            if bool(v.get("met")) and not met:
                note = "the model's quote was not found in the plan"
            new.append(CriterionResult(c["id"], label(c["text"], lang), met, quote if met else None, note))
        rv.criteria = new
        rv.score = _score(new, text)
        rv.status = status_for(rv.score, text)
        if rv.score < old_score:
            rv.criteria, rv.score, rv.status, rv.method = old_crit, old_score, old_status, "rules"
        else:
            rv.critique = masker.unmask(str(res.get("critique", "")))[:600]
            rv.method = "model"


def overall(reviews: list[SectionReview]) -> int:
    total = sum(r.weight for r in reviews) or 1.0
    return int(round(sum(r.score * r.weight for r in reviews) / total))
