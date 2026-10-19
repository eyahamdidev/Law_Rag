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


# --------------------------------------------------------------------------------------
# deterministic plan rules: each hit quotes the plan's own text (max 12 words). Python only.
# --------------------------------------------------------------------------------------
_HYPE_RE = re.compile(
    r"very positive|billions?|a good share|huge market|no competition|better because of our ai|motivated|promising|more modern",
    re.I)
_SOURCE_RE = re.compile(r"source|study|ministry|survey|statista|estimat|report|enqu[êe]te|[ée]tude|sondage", re.I)
_MARKET_FIG_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:billion|million|milliard|mrd|md)\b", re.I)
_ASK_NUM_RE = re.compile(r"(?:seeking|raising|need|looking for|besoin|recherchons|levons)[^.!?]{0,80}?\d[\d\s.,]{3,}", re.I)
_PRICE_LATER_RE = re.compile(r"^(later|tbd|to be (?:defined|decided)|plus tard|[àa] d[ée]finir|not set|n/a)\.?$", re.I)
_USE_OF_FUNDS_RE = re.compile(r"use of funds|used to|will be used|servira|serviront|affectation|allocated to", re.I)
_MOSTLY_SALARIES_RE = re.compile(r"mostly salar|essentially salar|essentiellement des salaires|principalement des salaires", re.I)
_HARDWARE_RE = re.compile(r"hardware|device|mat[ée]riel|machine|[ée]quipement", re.I)
_SUPPLIER_RE = re.compile(r"supplier|fournisseur|unit cost|co[ûu]t unitaire|per unit|piece price", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _short_quote(sentence: str) -> str:
    words = sentence.strip().split()
    q = " ".join(words[:12])
    return q + ("…" if len(words) > 12 else "")


def _sentence_with(text: str, *needles: str) -> str | None:
    for s in _SENT_SPLIT.split(text):
        if all(n.lower() in s.lower() for n in needles):
            return s
    return None


def run_plan_rules(text: str, values: dict, derived: dict | None) -> list[Weakness]:
    """Quote-backed deterministic critiques of the plan text and the answers. Max 6 items."""
    out: list[Weakness] = []
    sentences = _SENT_SPLIT.split(text or "")
    for s in sentences:  # unsupported claims: one hit is enough, they read the same
        if _HYPE_RE.search(s):
            sid = "market_analysis" if _MARKET_FIG_RE.search(s) else "project_description"
            out.append(Weakness("clarity_tone", "The plan states enthusiasm or scale with nothing behind it.",
                                "Replace the claim with a fact (a number, a name, a date) or delete it.", "medium",
                                _short_quote(s), sid, "rules"))
            break
    for s in sentences:  # a market figure with no source
        if _MARKET_FIG_RE.search(s) and not _SOURCE_RE.search(s):
            out.append(Weakness("market_realism", "A market size is given without any source.",
                                "Name where the figure comes from (study, ministry, survey) or mark it as an estimate.", "high",
                                _short_quote(s), "market_analysis", "rules"))
    if derived and derived.get("revenue"):  # every year pair above 3x, each quoted
        rev = derived["revenue"]
        for t in range(1, len(rev)):
            a, b = rev[t - 1], rev[t]
            if a and b is not None and a > 0 and b / a >= 4.0:
                s = next((s_ for s_ in sentences if str(int(a)) in re.sub(r"\D", "", s_) and str(int(b)) in re.sub(r"\D", "", s_)), None)
                out.append(Weakness("financial_flaws", f"Revenue grows {b / a:.1f}x from {derived['years'][t - 1]} to {derived['years'][t]} with no stated driver.",
                                    "State what makes that growth happen (customers, price, channels) or lower the figure.", "medium",
                                    _short_quote(s) if s else None, None if s else "financial_projections", "rules"))
    ask = values.get("funding_need_amount")
    if ask and not values.get("capex_items") and not _USE_OF_FUNDS_RE.search(text or ""):
        s = _sentence_with(text, str(int(ask))) if ask == int(ask) else _ASK_NUM_RE.search(text)
        out.append(Weakness("financial_flaws", "The plan asks for money but never says what it will be spent on.",
                            "Break the ask down by use (equipment, working capital, hiring).", "high",
                            _short_quote(s) if isinstance(s, str) else (_short_quote(s.group(0)) if s else None),
                            "financing_plan", "rules"))
    pricing = values.get("pricing")
    if not pricing or _PRICE_LATER_RE.match(str(pricing).strip()):
        s = _sentence_with(text, "price") or _sentence_with(text, "prix")
        out.append(Weakness("market_realism", "No price is stated, so revenue is an unsupported guess.",
                            "State the price per unit or per plan, and how it was set.", "high",
                            _short_quote(s) if s else None, "market_analysis", "rules"))
    for s in sentences:  # "mostly salaries" with no numbers
        if _MOSTLY_SALARIES_RE.search(s) and not re.search(r"\d", s):
            out.append(Weakness("financial_flaws", "A cost is called 'mostly salaries' with no figure attached.",
                                "Give the payroll number (headcount x gross salary) or the share of costs.", "medium",
                                _short_quote(s), "financial_projections", "rules"))
    hw = next((s for s in sentences if _HARDWARE_RE.search(s)), None)
    all_text = " ".join(str(v) for v in values.values() if isinstance(v, str)) + " " + (text or "")
    if hw and not _SUPPLIER_RE.search(all_text):
        out.append(Weakness("execution_risk", "A physical product with no supplier or unit cost anywhere in the plan.",
                            "Name the supplier and the unit cost of what you build or resell.", "medium",
                            _short_quote(hw), "operations", "rules"))
    out.sort(key=lambda w: SEV_ORDER.get(w.severity, 1))
    return out[:6]


def _quote_ok(quote: str, text: str) -> bool:
    q = re.sub(r"\s+", " ", fold(quote)).strip(" .…")
    t = re.sub(r"\s+", " ", fold(text))
    return len(q) >= 8 and q in t


def critique(text: str, sections: dict[str, dict], reviews, *, lang: str, llm: LLMClient, masker: Masker,
             trace: Trace, use_llm: bool = True, values: dict | None = None, derived: dict | None = None) -> Critique:
    # generic absence/thin items removed: every finding must quote the plan's own words
    base = run_plan_rules(text, values or {}, derived)
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
