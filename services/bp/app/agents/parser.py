"""Parser agent: map the uploaded plan onto the template skeleton.

Two layers, so the benchmark can compare them (spec: section-mapping accuracy):

* ``keywords``  deterministic. Headings first, then keyword density in the body.
* ``llm``       asks the model only about segments the keywords could not place.

Financial tables are read deterministically by row label. The model never
invents a number here: it only chooses a section name for a piece of text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app import prompts
from app.agents.common import Trace
from app.agents.common import fold as norm  # accent-insensitive matching on both sides
from app.config import SERVICE_ROOT
from app.financial import FinancialModel
from app.intake import Block, Document, Table
from app.llm import LLMClient, LLMUnavailable
from app.masking import Masker
from app.questionnaire import GOVERNORATES, ParseError, parse_number
from app.templates import section_index

CURRENCY_PATTERNS = [("EUR", r"\beuros?\b|€|\beur\b"), ("MAD", r"\bmad\b|dirham"), ("USD", r"\busd\b|\$|dollar")]
TND_PATTERN = r"\btnd\b|\bdt\b|dinar|دينار"


@dataclass
class Segment:
    heading: str
    blocks: list[Block] = field(default_factory=list)
    section_id: str | None = None
    confidence: float = 0.0
    method: str = "none"

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)

    @property
    def page(self) -> int | None:
        return next((b.page for b in self.blocks if b.page), None)

    @property
    def bbox(self):
        return next((b.bbox for b in self.blocks if b.bbox), None)


@dataclass
class ParsedPlan:
    sections: dict[str, dict] = field(default_factory=dict)  # id -> {text, segments, confidence, method}
    unmapped: list[dict] = field(default_factory=list)
    model: FinancialModel = field(default_factory=FinancialModel)
    facts: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ segmentation
def segment(doc: Document) -> list[Segment]:
    heads = sum(1 for b in doc.blocks if b.kind == "heading")
    segs: list[Segment] = []
    if heads >= 2:
        cur = Segment(heading="")
        for b in doc.blocks:
            if b.kind == "heading":
                if cur.blocks or cur.heading:
                    segs.append(cur)
                cur = Segment(heading=b.text)
            else:
                cur.blocks.append(b)
        if cur.blocks or cur.heading:
            segs.append(cur)
    else:  # no usable headings: judge paragraph by paragraph
        segs = [Segment(heading="", blocks=[b]) for b in doc.blocks if len(b.text) > 25]
    return segs


# ------------------------------------------------------------------ keyword mapping
def _kw(sec: dict, lang_keys=("fr", "en", "ar")) -> list[str]:
    out: list[str] = []
    for lg in lang_keys:
        out += [norm(k) for k in sec["title_keywords"].get(lg, [])]
    return out


def _body_kw(sec: dict) -> list[str]:
    out = _kw(sec)
    for c in sec["criteria"]:
        for lg in ("fr", "en", "ar"):
            out += [norm(k) for k in c["keywords"].get(lg, [])]
    return list(dict.fromkeys(out))


def score_segment(seg: Segment, template: dict) -> list[tuple[str, float]]:
    head, body = norm(seg.heading), norm(seg.text)
    scores = []
    for sec in template["sections"]:
        s = 0.0
        hits = [k for k in _kw(sec) if k and k in head]
        if hits:
            s += 3.0 + 0.5 * (len(hits) - 1)
        distinct = {k for k in _body_kw(sec) if len(k) >= 4 and k in body}
        s += min(len(distinct), 6) * 0.3
        scores.append((sec["id"], s))
    return sorted(scores, key=lambda x: -x[1])


def map_keywords(segs: list[Segment], template: dict, threshold: float = 1.0) -> None:
    for seg in segs:
        ranked = score_segment(seg, template)
        best, second = ranked[0], ranked[1]
        if best[1] >= threshold:
            seg.section_id, seg.method = best[0], "keywords"
            seg.confidence = round(min(1.0, best[1] / 4.0) * (1.0 if best[1] - second[1] >= 0.5 else 0.6), 2)
        else:
            seg.section_id, seg.method, seg.confidence = None, "none", 0.0


def map_llm(segs: list[Segment], template: dict, llm: LLMClient, masker: Masker, lang: str, trace: Trace) -> None:
    """Ask the model about unplaced or ambiguous segments only."""
    todo = [i for i, s in enumerate(segs) if s.section_id is None or s.confidence < 0.6]
    if not todo or not llm.available:
        return
    p = prompts.load("parser")
    ids = {s["id"] for s in template["sections"]}
    catalogue = "\n".join(f"- {s['id']}: {s['title']['en']} / {s['title']['fr']}" for s in template["sections"])
    items = [{"i": i, "heading": masker.mask(segs[i].heading)[:120], "excerpt": masker.mask(segs[i].text)[:400]} for i in todo[:40]]
    import json

    user = prompts.render(p["text"], sections=catalogue, items=json.dumps(items, ensure_ascii=False))
    from app.config import model_for

    model = model_for("llm_fast")
    with trace.step("parser.llm", model=model, prompt_id=prompts.ref(p)):
        try:
            out = llm.chat_json(model=model, system="You map plan segments to template sections. Reply with JSON only.", user=user, schema=p.get("output_schema"))
        except LLMUnavailable as exc:
            trace.note(f"parser.llm skipped: {exc}")
            return
    for m in out.get("mapping", []):
        try:
            i, sid = int(m["i"]), m["section_id"]
        except (KeyError, TypeError, ValueError):
            continue
        if i in todo and sid in ids:
            segs[i].section_id, segs[i].method = sid, "llm"
            segs[i].confidence = float(min(max(m.get("confidence", 0.7), 0), 1))


# ------------------------------------------------------------------ tables -> financial model
ROW_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("total_costs", re.compile(r"total\s+(des\s+)?(charges|costs|expenses)|charges\s+totales|اجمالي")),
    ("net_income", re.compile(r"r[ée]sultat\s+net|net\s+(income|profit|result)|b[ée]n[ée]fice\s+net|النتيجة الصافية")),
    ("cogs", re.compile(r"achats|co[uû]t\s+(des|de)|cost\s+of\s+(goods|sales)|cogs|mati[eè]res|direct\s+costs")),
    ("revenue", re.compile(r"chiffre\s+d.affaires|^ca\b|ventes|revenue(?!\s+specific)|turnover|(?<!unit )sales|رقم المعاملات")),
    ("payroll", re.compile(r"charges?\s+de\s+personnel|masse\s+salariale|salaires|payroll|personnel\s+costs|staff\s+costs")),
    ("depreciation", re.compile(r"dotations?|amortissements?|depreciation|amortization")),
    ("interest", re.compile(r"charges?\s+financi[eè]res|int[ée]r[êe]ts|interest")),
    ("tax", re.compile(r"imp[ôo]t\s+sur\s+(les\s+)?(soci[ée]t[ée]s|b[ée]n[ée]fices)|^is\b|income\s+tax|corporate\s+tax")),
    ("opex", re.compile(r"charges?\s+d.exploitation|autres\s+charges|frais\s+g[ée]n[ée]raux|services\s+ext[ée]rieurs|charges\s+externes|operating\s+(costs|expenses)|opex|overheads")),
    ("capex", re.compile(r"acquisitions?\s+d.immobilisations|investissements?\b|capex|capital\s+expenditure")),
    ("debt_service", re.compile(r"annuit[ée]s?|service\s+de\s+la\s+dette|remboursement.*(cr[ée]dit|emprunt)|debt\s+service|loan\s+payment")),
]
YEAR_CELL = re.compile(r"^(?:(?:19|20)\d{2}|an(?:n[ée]e)?\s*\d|year\s*\d|y\s*\d|a\s*\d|n(?:\s*\+\s*\d)?)$", re.I)
USES_TOTAL = re.compile(r"total\s+(des\s+)?emplois|total\s+uses|total\s+investissements?|co[uû]t\s+total\s+du\s+projet")
SOURCES_TOTAL = re.compile(r"total\s+(des\s+)?ressources|total\s+sources|total\s+financement")
SRC_KIND = [
    ("own_funds", re.compile(r"fonds\s+propres|apport|capital|own\s+funds|equity|autofinancement")),
    ("loan", re.compile(r"emprunt|cr[ée]dit|pr[êe]t|loan|bfpme|bancaire")),
    ("grant", re.compile(r"subvention|prime|grant|don\b|subsidy")),
]


def _num(cell: str) -> float | None:
    c = (cell or "").strip()
    if not c or not re.search(r"\d", c):
        return None
    neg = c.startswith("(") and c.endswith(")")
    if c.startswith("-") or c.startswith("\u2212"):
        neg, c = True, c[1:]
    c = re.sub(r"(?i)\s*(?:tnd|dt|usd|eur|mad|dinars?)\b|[$€£]", "", c).strip("() ")
    c = c.replace("%", "").strip()
    try:
        v = parse_number(c)
    except ParseError:
        return None
    return -v if neg else v


def _year_cols(rows: list[list[str]]) -> tuple[int, list[int], list[str]] | None:
    for ri, row in enumerate(rows[:6]):
        cols = [ci for ci, c in enumerate(row) if YEAR_CELL.match(c.strip())]
        if len(cols) >= 2:
            return ri, cols, [row[ci].strip() for ci in cols]
    return None


AMOUNT = r"(\d[\d  ]*(?:[.,]\d+)?)\s*(k|m|md|millions?|mille|thousand|billion)?\b"
REV_KEY = re.compile(r"(?:revenue|revenues|arr|sales|turnover|chiffre\s+d.affaires|\bca\b)", re.I)
YEAR_MARK = re.compile(r"\b(?:year|an|ann[ée]e|y)\s*(\d)\b", re.I)
ASK = re.compile(r"(?:we\s+need|seeking|raising|seed\s+need|funding\s+(?:need|ask)|besoin\s+de|nous\s+cherchons|lev[ée]e\s+de)\D{0,25}?" + AMOUNT, re.I)
UNITS = {"k": 1e3, "thousand": 1e3, "mille": 1e3, "m": 1e6, "million": 1e6, "millions": 1e6, "md": 1e9, "billion": 1e9}


def _amount(num: str, unit: str | None) -> float | None:
    try:
        v = parse_number(num.replace("\u00a0", " ").strip())
    except ParseError:
        return None
    return v * UNITS.get((unit or "").lower(), 1.0)


def prose_revenue(text: str) -> tuple[list[str], list[float]] | None:
    """Revenue by year when the plan states it in sentences: 'Year 1 revenue 400k, Year 2 2M' or 'Year 1: 150 accounts, ARR 520k'."""
    flat = re.sub(r"\s+", " ", text)
    marks = list(YEAR_MARK.finditer(flat))
    best: dict[int, float] = {}
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(flat)
        seg = flat[mk.end(): min(end, mk.end() + 140)]
        lead = flat[max(0, mk.start() - 40): mk.start()]
        km = REV_KEY.search(seg)
        v = None
        if not km:  # 'Revenue: 50 000 TND in year 1' — the amount sits just before the year mark
            tm = re.search(AMOUNT + r"\s*(?:tnd|dt|eur|usd|mad)?\s*(?:in|by|during|on|at|en|dans|sur|pour|de)?\s*$", lead, re.I)
            if tm:
                tv = _amount(tm.group(1), tm.group(2))
                if tv and tv not in best.values():
                    v = tv
        if v is None:
            if km:
                am = re.search(AMOUNT, seg[km.end():], re.I)
            elif REV_KEY.search(lead) or best:  # 'Revenue: Year 1 50k, Year 2 400k' or a series already under way
                am = re.match(r"\W{0,3}" + AMOUNT, seg, re.I)
            else:
                am = None
            v = _amount(am.group(1), am.group(2)) if am else None
        if v:
            best.setdefault(int(mk.group(1)), v)
    if len(best) < 2:
        return None
    yrs = sorted(best)
    return [f"Y{y}" for y in yrs], [best[y] for y in yrs]


def prose_funding_ask(text: str) -> float | None:
    m = ASK.search(re.sub(r"\s+", " ", text))
    return _amount(m.group(1), m.group(2)) if m else None


def extract_financials(doc: Document) -> FinancialModel:
    m = FinancialModel(origin="document")
    found_any = False
    for tbl in doc.tables:
        rows = tbl.rows
        yc = _year_cols(rows)
        if yc:
            hdr, cols, labels = yc
            if not m.years:
                m.years = labels
                for name in ("revenue", "cogs", "payroll", "opex", "depreciation", "interest", "tax", "capex",
                             "total_costs_stated", "net_income_stated", "debt_service_stated"):
                    setattr(m, name, [None] * len(labels))
            n = min(len(labels), len(m.years))
            for row in rows[hdr + 1:]:
                first = cols[0]
                label = norm(next((c for c in row[:first] if c.strip() and not re.fullmatch(r"[\W\d_]*", c.strip())), ""))
                if not label:
                    continue
                for key, pat in ROW_PATTERNS:
                    if pat.search(label):
                        attr = {"total_costs": "total_costs_stated", "net_income": "net_income_stated", "debt_service": "debt_service_stated"}.get(key, key)
                        cur = getattr(m, attr)
                        vals = [_num(row[c]) if c < len(row) else None for c in cols[:n]]
                        if any(v is not None for v in vals) and all(x is None for x in cur[:n]):
                            for i in range(n):
                                cur[i] = vals[i]
                            m.evidence[attr.replace("_stated", "")] = {"page": tbl.page, "bbox": tbl.bbox, "row": row[0]}
                            found_any = True
                        break
            continue
        # uses and sources tables: label | amount (single or side by side)
        _read_funding(tbl, m)
        found_any = found_any or bool(m.uses or m.sources)
    if not found_any:
        pr = prose_revenue(doc.text)
        if pr:
            m.years, rev = pr
            for name in ("revenue", "cogs", "payroll", "opex", "depreciation", "interest", "tax", "capex",
                         "total_costs_stated", "net_income_stated", "debt_service_stated"):
                setattr(m, name, [None] * len(m.years))
            m.revenue = rev
            m.evidence["revenue"] = {"page": None, "bbox": None, "row": "stated in the text"}
            found_any = True
    if not found_any:
        m.origin = "none"
    return m


def _read_funding(tbl: Table, m: FinancialModel) -> None:
    for row in tbl.rows:
        cells = [c.strip() for c in row]
        pairs = []
        if len(cells) >= 4:
            pairs = [(cells[0], cells[1]), (cells[2], cells[3])]
        elif len(cells) >= 2:
            pairs = [(cells[0], cells[1])]
        for label, amount in pairs:
            nl, v = norm(label), _num(amount)
            if v is None or not nl:
                continue
            if USES_TOTAL.search(nl):
                m.uses_total_stated, m.evidence["uses_total"] = v, {"page": tbl.page, "bbox": tbl.bbox}
            elif SOURCES_TOTAL.search(nl):
                m.sources_total_stated, m.evidence["sources_total"] = v, {"page": tbl.page, "bbox": tbl.bbox}
            else:
                kind = next((k for k, p in SRC_KIND if p.search(nl)), None)
                if kind:
                    m.sources[kind] = m.sources.get(kind, 0.0) + v
                elif re.search(r"investissement|immobilisation|[ée]quipement|mat[ée]riel|local|logiciel|fonds\s+de\s+roulement|bfr|frais|capex|working\s+capital|machine", nl):
                    m.uses[label] = m.uses.get(label, 0.0) + v


# ------------------------------------------------------------------ facts
def extract_facts(doc: Document, model: FinancialModel) -> dict:
    text = doc.text
    facts: dict = {}
    for form in ("SUARL", "SARL", "SAS"):
        if re.search(rf"\b{form}\b", text):
            facts["legal_form"] = form
            break
    else:
        if re.search(r"\bSA\b|soci[ée]t[ée]\s+anonyme", text):
            facts["legal_form"] = "SA"
    low = norm(text)
    for g in GOVERNORATES:
        if re.search(rf"\b{re.escape(norm(g))}\b", low):
            facts["governorate"] = g
            break
    if model.uses_total_stated or model.uses:
        facts["total_investment"] = model.uses_total_stated or sum(model.uses.values())
    if "own_funds" in model.sources:
        facts["own_funds"] = model.sources["own_funds"]
    if "loan" in model.sources:
        facts["loan_amount"] = model.sources["loan"]
    if "grant" in model.sources:
        facts["grant_amount"] = model.sources["grant"]
    ask = prose_funding_ask(text)
    if ask and "funding_need_amount" not in facts:
        facts["funding_need_amount"] = ask
    if model.revenue and any(model.revenue) and "revenue_by_year" not in facts:
        facts["revenue_by_year"] = [x for x in model.revenue if x is not None]
    counts = {c: len(re.findall(pat, text or "", re.I)) for c, pat in CURRENCY_PATTERNS}
    foreign = max(counts, key=lambda c: counts[c]) if counts else None
    if foreign and counts[foreign] > len(re.findall(TND_PATTERN, text or "", re.I)):
        facts["currency"] = foreign  # stated currency wins over the Tunisian default; never converted
    first_block = next((re.sub(r"\s+", " ", b.text).strip() for b in doc.blocks if b.text.strip()), "")
    if first_block and len(first_block) <= 200 and "project_name" not in facts:
        facts["project_name"] = first_block  # the document title block is the project name
    return facts


FINANCE_TABLE = [
    ("financial_projections", re.compile(r"chiffre\s+d.affaires|r[ée]sultat|revenue|profit|tr[ée]sorerie|cash")),
    ("financing_plan", re.compile(r"ressources|financement|fonds\s+propres|emprunt|sources|loan|equity")),
    ("investment_plan", re.compile(r"emplois|investissement|immobilisation|capex|uses")),
]


def table_text(t: Table) -> str:
    return "\n".join(" | ".join(c for c in r if c) for r in t.rows)


def extract_facts_llm(doc: Document, llm: LLMClient, masker: Masker, trace: Trace) -> dict:
    """One extraction call over the FULL document text (the regex layer only sees tables and money patterns)."""
    if not llm.available:
        return {}
    p = prompts.load("parser_facts")
    from app.config import model_for

    model = model_for("llm_fast")
    text = re.sub(r"\s+", " ", masker.mask(doc.text)).strip()
    if len(text) > 24000:
        text = text[:24000]
    with trace.step("parser.facts", model=model, prompt_id=prompts.ref(p)):
        try:
            out = llm.chat_json(model=model, system="You extract stated facts from a business plan. Reply with JSON only.",
                                user=prompts.render(p["text"], plan_text=text), schema=p.get("output_schema"), max_tokens=2000)
        except LLMUnavailable as exc:
            trace.note(f"parser.facts skipped: {exc}")
            return {}
    clean: dict = {}
    for k, v in (out or {}).items():
        k = {"offer": "solution", "market_size": "market_size_note", "traction": "traction_note", "team": "founders",
             "ip": "ip_note", "awards": "awards_note", "permits": "permits_note"}.get(k, k)  # bank ids
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            v = [str(x).strip() for x in v if str(x).strip()]
            if not v:
                continue
            clean[k] = ("\n".join(f"- {x}" for x in v) if k in ("competitors", "risks") else v)
        elif isinstance(v, (int, float, str)):
            clean[k] = v
    return clean


def _dump_facts(facts: dict) -> None:
    """Audit trail for 'extraction returns almost nothing' reports: services/bp/tmp/facts_<name>.json."""
    try:
        name = re.sub(r"[^a-z0-9]+", "_", norm(str(facts.get("project_name") or "plan")).strip("_"))[:40] or "plan"
        folder = SERVICE_ROOT / "tmp"
        folder.mkdir(exist_ok=True)
        (folder / f"facts_{name}.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001  a dump failure must never break the run
        pass


# ------------------------------------------------------------------ entry point
def parse(doc: Document, template: dict, *, llm: LLMClient, masker: Masker, lang: str, trace: Trace, mode: str = "auto") -> ParsedPlan:
    plan = ParsedPlan(warnings=list(doc.warnings))
    with trace.step("parser.keywords"):
        segs = segment(doc)
        map_keywords(segs, template)
    if mode in ("auto", "llm"):
        if mode == "llm":
            for s in segs:
                s.section_id, s.confidence = None, 0.0
        map_llm(segs, template, llm, masker, lang, trace)
    idx = section_index(template)
    for s in segs:
        if s.section_id and s.section_id in idx:
            entry = plan.sections.setdefault(s.section_id, {"text": "", "segments": [], "confidence": 0.0, "method": s.method})
            entry["text"] = (entry["text"] + "\n" + s.text).strip() if entry["text"] else s.text
            entry["segments"].append({"heading": s.heading, "page": s.page, "bbox": s.bbox})
            entry["confidence"] = max(entry["confidence"], s.confidence)
            if s.method == "llm":
                entry["method"] = "llm"
        elif s.text.strip() or s.heading:
            plan.unmapped.append({"heading": s.heading, "page": s.page, "excerpt": s.text[:120]})
    with trace.step("parser.tables"):
        plan.model = extract_financials(doc)
        for t in doc.tables:
            joined = norm(table_text(t))
            for sid, pat in FINANCE_TABLE:
                if sid in idx and pat.search(joined):
                    entry = plan.sections.setdefault(sid, {"text": "", "segments": [], "confidence": 0.6, "method": "table"})
                    entry["text"] = (entry["text"] + "\n" + table_text(t)).strip()
                    entry["segments"].append({"heading": t.name or "table", "page": t.page, "bbox": t.bbox})
        plan.facts = extract_facts(doc, plan.model)
        llm_facts = extract_facts_llm(doc, llm, masker, trace)
        for k, v in llm_facts.items():  # mechanical facts (tables, governorate, currency) keep priority
            if k not in plan.facts:
                plan.facts[k] = v
        _dump_facts(plan.facts)
    return plan
