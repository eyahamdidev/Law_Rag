"""Plan-level critique: the critical weakness report and the preventative actions.

Voice and framework: a brutally honest angel investor, lead McKinsey auditor and
cynical risk officer, judging five dimensions (market realism, defensibility,
execution risk, financial flaws, clarity and tone).

Guards, same philosophy as the reviewer and the assessor:

* a weakness is only reported with evidence: an exact quote from the plan that
  must be found in the text, otherwise the weakness is discarded;
* the one exception is an absence claim ("there is no X anywhere"). It carries no
  quote but must point at a section id whose review is missing or weak, so the
  claim is checked against the deterministic section reviews before it is shown;
* the deterministic baseline (no model): the weakness report is built from the
  section reviews themselves, so the block always exists.
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
from app.templates import label as _label

MAX_TEXT = 8000
SEV_ORDER = {"high": 0, "medium": 1, "low": 2}

DIM_LABELS = {
    "market_realism": {"en": "Market realism", "fr": "Réalisme du marché", "ar": "واقعية السوق"},
    "defensibility": {"en": "Defensibility (moat)", "fr": "Défendabilité (avantage)", "ar": "قابلية الدفاع"},
    "execution_risk": {"en": "Execution risk", "fr": "Risque d'exécution", "ar": "خطر التنفيذ"},
    "financial_flaws": {"en": "Financial flaws", "fr": "Failles financières", "ar": "الثغرات المالية"},
    "clarity_tone": {"en": "Clarity and tone", "fr": "Clarté et ton", "ar": "الوضوح والأسلوب"},
}

SECTION_DIM = {
    "market_analysis": "market_realism", "market": "market_realism", "marketing_plan": "market_realism",
    "problem": "market_realism",
    "financial_projections": "financial_flaws", "financials_ask": "financial_flaws",
    "investment_plan": "financial_flaws", "financing_plan": "financial_flaws",
    "operations": "execution_risk", "human_resources": "execution_risk", "promoters_team": "execution_risk",
    "team": "execution_risk", "risks": "execution_risk", "legal_structure": "execution_risk",
    "business_model": "defensibility",
    "executive_summary": "clarity_tone", "project_description": "clarity_tone",
    "existing_activity": "clarity_tone", "extension_project": "clarity_tone", "impact": "clarity_tone",
}


def dimension_for_section(section_id: str) -> str:
    return SECTION_DIM.get(section_id, "execution_risk")


def dim_label(dimension: str, lang: str) -> str:
    return DIM_LABELS.get(dimension, {}).get(lang) or DIM_LABELS[dimension]["en"]


@dataclass
class Weakness:
    dimension: str
    why: str
    fix: str
    severity: str = "medium"
    quote: str | None = None
    section_id: str | None = None
    source: str = "rules"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Critique:
    weaknesses: list[Weakness] = field(default_factory=list)
    method: str = "rules"

    def to_dict(self) -> dict:
        return {"method": self.method, "weaknesses": [w.to_dict() for w in self.weaknesses]}

    def notes_for(self, section_id: str, section_text: str) -> list[str]:
        """Critic demands that concern one section: direct absence claims, or a quote found in that section's text."""
        folded = re.sub(r"\s+", " ", fold(section_text))
        out = []
        for w in self.weaknesses:
            hit = (w.section_id == section_id and not w.quote) or (
                w.quote and len(folded) > 0 and re.sub(r"\s+", " ", fold(w.quote)).strip(" .…") in folded)
            if hit:
                out.append(f"[{dim_label(w.dimension, 'en')}] {w.fix}")
        return out[:4]


def run_rules(reviews) -> list[Weakness]:
    out: list[Weakness] = []
    for rv in reviews:
        if not rv.required or rv.status not in ("missing", "weak"):
            continue
        if rv.status == "missing":
            why = f"The required section '{rv.title}' is absent from the plan."
        else:
            why = f"The section '{rv.title}' is present but thin (score {rv.score}/100)."
        unmet = [_label(c.text, "en") if isinstance(c.text, dict) else str(c.text) for c in rv.criteria if not c.met][:3]
        fix = ("Cover concretely: " + "; ".join(unmet) + ".") if unmet else f"Draft '{rv.title}' with concrete figures and named examples."
        out.append(Weakness(dimension_for_section(rv.section_id), why, fix, "high" if rv.status == "missing" else "medium",
                            None, rv.section_id, "rules"))
    return out


def _quote_ok(quote: str, text: str) -> bool:
    q = re.sub(r"\s+", " ", fold(quote)).strip(" .…")
    t = re.sub(r"\s+", " ", fold(text))
    return len(q) >= 8 and q in t


def critique(text: str, sections: dict[str, dict], reviews, *, lang: str, llm: LLMClient, masker: Masker,
             trace: Trace, use_llm: bool = True) -> Critique:
    base = run_rules(reviews)
    out = Critique(weaknesses=base, method="rules")
    if not (use_llm and llm.available) or not text.strip():
        return out
    p = prompts.load("critic")
    section_ids = ", ".join(rv.section_id for rv in reviews)
    already = ", ".join(rv.title for rv in reviews if rv.required and rv.status in ("missing", "weak")) or "none"
    user = prompts.render(p["text"], section_ids=section_ids, lang_name={"fr": "French", "ar": "Arabic", "en": "English"}[lang],
                          already=already, plan=masker.mask(text)[:MAX_TEXT])
    model = model_for("llm_main")
    with trace.step("critic.llm", model=model, prompt_id=prompts.ref(p)):
        try:
            res = llm.chat_json(model=model, system="You are a brutally honest angel investor and McKinsey-style auditor tearing a business plan apart. Reply with JSON only.",
                                user=user, schema=p.get("output_schema"), max_tokens=2000)
        except LLMUnavailable as exc:
            trace.note(f"critic.llm skipped: {exc}")
            return out
    review_by = {rv.section_id: rv for rv in reviews}
    seen_absence: set[str] = set()
    kept: list[Weakness] = []
    for item in res.get("weaknesses", []):
        if not isinstance(item, dict):
            continue
        dim = str(item.get("dimension", ""))
        why = str(item.get("why", "")).strip()
        fix = str(item.get("fix", "")).strip()
        if dim not in DIM_LABELS or not why or not fix:
            continue
        sev = str(item.get("severity", "medium")).lower()
        quote = masker.unmask(str(item.get("quote") or "")).strip() or None
        sid = str(item.get("section_id") or "").strip() or None
        if quote is not None:
            if not _quote_ok(quote, text):
                trace.note(f"critic: quote not found in the plan, weakness dropped ({dim})")
                continue
        elif sid is not None:
            rv = review_by.get(sid)
            if rv is None or rv.status not in ("missing", "weak"):
                trace.note(f"critic: absence claim about '{sid}' contradicts the section review, dropped ({dim})")
                continue
            seen_absence.add(sid)
        else:
            continue  # no quote and no verifiable section reference
        kept.append(Weakness(dim, why[:400], fix[:400], sev if sev in SEV_ORDER else "medium", quote[:200] if quote else None,
                             sid, "model"))
    # the model's absence claims replace the generic rules-based ones for the same section
    base = [w for w in base if w.section_id not in seen_absence]
    kept.sort(key=lambda w: SEV_ORDER[w.severity])
    return Critique(weaknesses=base + kept, method="rules+model")
