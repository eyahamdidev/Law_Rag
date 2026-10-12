"""Writer: draft a missing or weak section, flag every figure that is not in the facts.

Rule: the writer never presents an invented number as fact. Any number in a
draft that cannot be traced to the founder's answers, the plan, the profile or
the deterministic model gets a visible marker. ``guard`` enforces this after the
model has written, so the guarantee does not depend on the model obeying.

Without a model, a deterministic draft is assembled from the founder's own
answers, with placeholders for what is missing.
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
from app.questionnaire import BANK_BY_ID, ParseError, parse_number
from app.templates import label

MARKERS = {"en": "[to be confirmed by the founder]", "fr": "[à confirmer par le fondateur]", "ar": "[يؤكده الباعث]"}
ANY_MARKER = re.compile(r"\[(?:to be confirmed by the founder|à confirmer par le fondateur|يؤكده الباعث)\]", re.I)
NUM = re.compile(r"(?<![\w.\[])(\d{1,3}(?:[   ,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(\s*(?:%|k\b|m\b|millions?\b|mille\b|md\b))?", re.I)
LIST_ITEM = re.compile(r"^\s*\d{1,2}[.)]\s")
UNIT = re.compile(r"\s*(?:TND|DT|dinars?|euros?|EUR|USD|MD)\b|\s*[€$]", re.I)


@dataclass
class Draft:
    section_id: str
    title: str
    text: str
    flagged: list[dict] = field(default_factory=list)
    guidance: list[dict] = field(default_factory=list)
    method: str = "template"
    retried: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------- allowed numbers
def _collect(obj, out: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for m in NUM.finditer(obj):
            v = _value(m)
            if v is not None:
                out.add(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, out)


def allowed_numbers(*sources) -> set[float]:
    out: set[float] = set()
    for s in sources:
        _collect(s, out)
    return out


def _value(m: re.Match) -> float | None:
    raw, suffix = m.group(1), (m.group(2) or "").strip().lower()
    try:
        v = parse_number(raw)
    except ParseError:
        return None
    if suffix == "k":
        v *= 1e3
    elif suffix in ("m", "million", "millions"):
        v *= 1e6
    elif suffix == "mille":
        v *= 1e3
    elif suffix == "md":
        v *= 1e9
    return v


def _is_allowed(v: float, allowed: set[float], pct: bool) -> bool:
    for a in allowed:
        tol = 0.51 if pct else max(0.5, 0.005 * abs(a))
        if abs(a - v) <= tol:
            return True
        if pct and abs(a * 100 - v) <= 0.51:  # ratios stored as 0.35 and written as 35%
            return True
    return False


def guard(text: str, allowed: set[float], lang: str) -> tuple[str, list[dict]]:
    """Mark every number that is not traceable. Returns the marked text and the flagged items."""
    marker = MARKERS.get(lang, MARKERS["en"])
    flagged: list[dict] = []
    out, last = [], 0
    for m in NUM.finditer(text):
        start, end = m.span()
        line_start = text.rfind("\n", 0, start) + 1
        if LIST_ITEM.match(text[line_start:end + 2]) and start - line_start <= 3:
            continue
        if text[max(0, start - 2):start] == "[[" or ANY_MARKER.search(text[max(0, line_start):start][-60:] or ""):
            pass
        raw = m.group(1)
        if re.fullmatch(r"(19|20)\d{2}", raw) and not m.group(2):
            continue  # a year
        v = _value(m)
        if v is None:
            continue
        pct = (m.group(2) or "").strip() == "%"
        if _is_allowed(v, allowed, pct):
            continue
        um = UNIT.match(text, end)
        if um:
            end = um.end()
        # already followed by a marker?
        after = text[end:end + 60]
        if ANY_MARKER.match(after.lstrip(" )")) or ANY_MARKER.match(after):
            flagged.append({"value": m.group(0).strip(), "context": text[max(0, start - 30):end + 20].strip(), "marked_by": "writer"})
            continue
        out.append(text[last:end])
        out.append(" " + marker)
        last = end
        flagged.append({"value": m.group(0).strip(), "context": text[max(0, start - 30):end + 20].strip(), "marked_by": "guard"})
    out.append(text[last:])
    return "".join(out), flagged


def unflagged_count(text: str, allowed: set[float]) -> int:
    """Independent check used by the evaluation: untraceable numbers with no marker after them."""
    n = 0
    for m in NUM.finditer(text):
        raw = m.group(1)
        line_start = text.rfind("\n", 0, m.start()) + 1
        if LIST_ITEM.match(text[line_start:m.end() + 2]) and m.start() - line_start <= 3:
            continue
        if re.fullmatch(r"(19|20)\d{2}", raw) and not m.group(2):
            continue
        v = _value(m)
        if v is None or _is_allowed(v, allowed, (m.group(2) or "").strip() == "%"):
            continue
        e = m.end()
        um = UNIT.match(text, e)
        if um:
            e = um.end()
        if not ANY_MARKER.match(text[e:e + 60].lstrip()):
            n += 1
    return n


# ---------------------------------------------------------------------------- deterministic draft
def _fmt(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (int, float)):
        return f"{v:,.0f}".replace(",", " ") if abs(v) >= 1000 else (f"{v:g}")
    return str(v)


def _render_value(qid: str, v, derived: dict | None) -> str:
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return "; ".join(f"{i['label']}: {_fmt(i['amount'])} TND" for i in v)
    if isinstance(v, list):
        return ", ".join(_fmt(x) for x in v)
    q = BANK_BY_ID.get(qid)
    if q and q.type == "pct":
        return f"{_fmt(v)} %"
    if q and q.type == "number":
        return f"{_fmt(v)} TND" if "TND" in q.en else _fmt(v)
    return str(v)


def template_draft(sec: dict, values: dict, derived: dict | None, lang: str) -> str:
    """Assemble the section from the founder's own answers. Missing items become placeholders."""
    marker = MARKERS.get(lang, MARKERS["en"])
    lines: list[str] = []
    for qid in sec["questions"]:
        q = BANK_BY_ID.get(qid)
        if q is None:
            continue
        lab = {"en": q.en, "fr": q.fr, "ar": q.ar}.get(lang, q.en)
        if qid in values:
            lines.append(f"{lab}: {_render_value(qid, values[qid], derived)}.")
        else:
            lines.append(f"{lab}: {marker}")
    if sec["id"] == "financial_projections" and derived and derived.get("revenue") and any(derived["revenue"]):
        yrs = derived["years"]
        lines.append("Revenue: " + ", ".join(f"{y} {_fmt(v)} TND" for y, v in zip(yrs, derived["revenue"])) + ".")
        lines.append("Net result: " + ", ".join(f"{y} {_fmt(v)} TND" for y, v in zip(yrs, derived["net_income"])) + ".")
        be = derived.get("break_even_year")
        lines.append(f"Break-even reached in {be}." if be else "Break-even is not reached within the horizon.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------- model draft
def draft_section(
    sec: dict,
    *,
    values: dict,
    derived: dict | None,
    existing: str,
    guidance: list[dict],
    lang: str,
    llm: LLMClient,
    masker: Masker,
    trace: Trace,
    extra_numbers: set[float] | None = None,
) -> Draft:
    title = label(sec["title"], lang)
    allowed = allowed_numbers(values, derived or {}, existing, extra_numbers or set())
    base = template_draft(sec, values, derived, lang)
    d = Draft(section_id=sec["id"], title=title, text=base, guidance=[{k: g[k] for k in ("id", "title", "score", "score_kind")} for g in guidance])
    if not llm.available:
        d.text, d.flagged = guard(base, allowed, lang)
        return d
    p = prompts.load("writer")
    model = model_for("llm_main")
    facts = {k: v for k, v in values.items() if k not in ("founders",)}  # names stay local unless the founder gave them as text
    facts_json = masker.mask(json.dumps({"answers": facts, "model": _slim(derived)}, ensure_ascii=False))
    crit = "\n".join(f"- {label(c['text'], lang)}" for c in sec["criteria"])
    adv = "\n".join(f"- {g['title']}: {g['text']}" for g in guidance)
    feedback = ""
    for attempt in (0, 1):
        user = prompts.render(p["text"], section=title, language={"fr": "French", "ar": "Arabic", "en": "English"}[lang],
                              criteria=crit, guidance=adv, facts=facts_json, existing=masker.mask(existing)[:1500],
                              marker=MARKERS.get(lang, MARKERS["en"]), feedback=feedback)
        with trace.step("writer.llm" if attempt == 0 else "writer.llm.retry", model=model, prompt_id=prompts.ref(p)):
            try:
                out = llm.chat_json(model=model, system="You draft business-plan sections. Reply with JSON only.", user=user,
                                    schema=p.get("output_schema"), max_tokens=1500)
            except LLMUnavailable as exc:
                trace.note(f"writer.llm skipped: {exc}")
                d.text, d.flagged = guard(base, allowed, lang)
                return d
        text = masker.unmask(str(out.get("text", ""))).strip()
        if not text:
            break
        bad = unflagged_count(text, allowed)
        if bad and attempt == 0:
            feedback = f"\nYour previous draft contained {bad} figure(s) that are not in the facts. Remove them or write the marker right after each one."
            d.retried = True
            continue
        d.text, d.flagged = guard(text, allowed, lang)
        d.method = "model"
        return d
    d.text, d.flagged = guard(base, allowed, lang)
    return d


def _slim(derived: dict | None) -> dict:
    if not derived:
        return {}
    keep = ("years", "revenue", "ebitda", "net_income", "cash_end", "break_even_year", "tax_rate_pct")
    return {k: derived[k] for k in keep if k in derived}


def _para_with_markers_text(doc, text: str) -> None:
    """Add paragraphs to a python-docx document, highlighting the confirm markers."""
    from docx.enum.text import WD_COLOR_INDEX

    for line in text.split("\n"):
        p = doc.add_paragraph()
        pos = 0
        for m in ANY_MARKER.finditer(line):
            p.add_run(line[pos:m.start()])
            r = p.add_run(m.group(0))
            r.font.highlight_color = WD_COLOR_INDEX.YELLOW
            pos = m.end()
        p.add_run(line[pos:])
