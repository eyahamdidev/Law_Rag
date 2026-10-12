"""Compose a readable business plan from the founder's answers, and export it as a Word file.

Nothing here invents content. Each section is the founder's own words under a clear sub-heading,
plus figures computed from the numbers they gave (tables, totals, projection). Anything missing is listed
under "To complete" and in an open-items page, never filled with a guess.
With a model key, ``pipeline`` may polish each section; the figure guard still marks every number
that is not in the inputs.
"""

from __future__ import annotations

import io

from docx import Document
from docx.shared import Inches, Pt

from app.agents.writer import MARKERS, _fmt, _para_with_markers_text  # noqa: F401
from app.questionnaire import BANK_BY_ID
from app.templates import label

SUB = {
    "problem": {"en": "The problem", "fr": "Le problème", "ar": "المشكل"},
    "solution": {"en": "The offer", "fr": "L'offre", "ar": "العرض"},
    "differentiator": {"en": "What makes it different", "fr": "Ce qui nous différencie", "ar": "ما يميزنا"},
    "target_customers": {"en": "Target customers", "fr": "Clientèle cible", "ar": "الحرفاء المستهدفون"},
    "market_size_note": {"en": "Market size", "fr": "Taille du marché", "ar": "حجم السوق"},
    "competitors": {"en": "Competitors and alternatives", "fr": "Concurrents et alternatives", "ar": "المنافسون والبدائل"},
    "pricing": {"en": "Pricing", "fr": "Prix", "ar": "الأسعار"},
    "channels": {"en": "Sales channels", "fr": "Canaux de vente", "ar": "قنوات البيع"},
    "founders": {"en": "Founders and roles", "fr": "Promoteurs et rôles", "ar": "الباعثون وأدوارهم"},
    "key_skills": {"en": "Experience and skills", "fr": "Expérience et compétences", "ar": "الخبرة والمهارات"},
    "production_means": {"en": "Equipment and premises", "fr": "Équipements et locaux", "ar": "التجهيزات والمحلات"},
    "suppliers": {"en": "Suppliers", "fr": "Fournisseurs", "ar": "المزودون"},
    "risks": {"en": "Main risks and how we handle them", "fr": "Principaux risques et mesures", "ar": "المخاطر وسبل معالجتها"},
    "extension_goal": {"en": "The extension", "fr": "L'extension", "ar": "التوسعة"},
}
TITLES = {"cover_sub": {"en": "Business plan: working draft", "fr": "Business plan : version de travail", "ar": "خطة العمل: مسودة"},
          "banner": {"en": "Draft generated from your answers. Yellow markers show what is still missing or must be confirmed by you. It is not a final or approved plan.",
                     "fr": "Version générée à partir de vos réponses. Les repères jaunes indiquent ce qui manque ou doit être confirmé par vous. Ce n'est pas un plan final ni validé.",
                     "ar": "مسودة أنشئت من إجاباتكم. العلامات الصفراء تبين ما ينقص أو يجب أن تؤكدوه. ليست خطة نهائية."},
          "key": {"en": "Key figures", "fr": "Chiffres clés", "ar": "أرقام أساسية"},
          "todo": {"en": "To complete", "fr": "À compléter", "ar": "للاستكمال"},
          "open": {"en": "Open items", "fr": "Points à compléter", "ar": "نقاط مفتوحة"},
          "uses": {"en": "Uses", "fr": "Emplois", "ar": "الاستخدامات"}, "sources": {"en": "Sources", "fr": "Ressources", "ar": "الموارد"},
          "proj": {"en": "Projection (computed from your figures)", "fr": "Projection (calculée à partir de vos chiffres)", "ar": "التوقعات"},
          "total": {"en": "Total", "fr": "Total", "ar": "المجموع"},
          "none_listed": {"en": "No detail was given.", "fr": "Aucun détail fourni.", "ar": "لا تفاصيل."}}


def _t(key: str, lang: str) -> str:
    return TITLES[key].get(lang) or TITLES[key]["en"]


def _qlabel(qid: str, lang: str) -> str:
    if qid in SUB:
        return SUB[qid].get(lang) or SUB[qid]["en"]
    q = BANK_BY_ID[qid]
    return {"en": q.en, "fr": q.fr, "ar": q.ar}.get(lang, q.en)


def _num(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def compose_section(sec: dict, values: dict, derived: dict | None, lang: str) -> dict:
    """Return {id, title, blocks, missing}. A block is ('h', text) | ('p', text) | ('ul', [text]) | ('table', header, rows)."""
    marker = MARKERS.get(lang, MARKERS["en"])
    blocks: list[tuple] = []
    missing: list[str] = []
    figures: list[str] = []
    for qid in sec["questions"]:
        q = BANK_BY_ID.get(qid)
        if q is None or q.type == "year_series":
            continue
        if qid not in values:
            if q.required or sec["id"] in ("risks",):
                missing.append(_qlabel(qid, lang))
            continue
        v = values[qid]
        if q.type in ("text", "longtext"):
            blocks += [("h", _qlabel(qid, lang)), ("p", str(v))]
        elif q.type == "items":
            continue  # shown as a table below
        elif q.type == "bool":
            figures.append(f"{_qlabel(qid, lang)}: {'yes' if v else 'no'}")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            unit = " TND" if q.type == "number" and "TND" in q.en else (" %" if q.type == "pct" else "")
            figures.append(f"{_qlabel(qid, lang)}: {_num(v)}{unit}" if abs(v) >= 1000 else f"{_qlabel(qid, lang)}: {v:g}{unit}")
        else:
            figures.append(f"{_qlabel(qid, lang)}: {v}")
    if figures:
        blocks.append(("h", _t("key", lang)))
        blocks.append(("ul", figures))

    sid = sec["id"]
    if sid == "investment_plan" and values.get("capex_items"):
        rows = [[i["label"], _num(i["amount"])] for i in values["capex_items"]]
        rows.append([_t("total", lang), _num(sum(i["amount"] for i in values["capex_items"]))])
        blocks.append(("table", [_t("uses", lang), "TND"], rows))
    if sid == "financing_plan":
        src = [(k, values[k]) for k in ("own_funds", "loan_amount", "grant_amount") if values.get(k)]
        if src:
            rows = [[_qlabel(k, lang), _num(v)] for k, v in src]
            rows.append([_t("total", lang), _num(sum(v for _, v in src))])
            blocks.append(("table", [_t("sources", lang), "TND"], rows))
            ti = values.get("total_investment")
            gap = (ti - sum(v for _, v in src)) if ti else None
            if gap and abs(gap) > 1:
                blocks.append(("p", f"{marker} " + ({"en": f"Total investment is {_num(ti)} TND but the listed sources add up to {_num(sum(v for _, v in src))} TND.",
                                                       "fr": f"L'investissement total est de {_num(ti)} TND mais les ressources listées font {_num(sum(v for _, v in src))} TND.",
                                                       "ar": ""}[lang] if lang in ("en", "fr") else "")))
    if sid == "financial_projections" and derived and derived.get("revenue") and any(derived["revenue"]):
        yrs = derived["years"]
        rows = []
        for key, lab in (("revenue", {"en": "Revenue", "fr": "Chiffre d'affaires"}), ("ebitda", {"en": "EBITDA", "fr": "EBE"}),
                         ("net_income", {"en": "Net result", "fr": "Résultat net"}), ("cash_end", {"en": "Year-end cash", "fr": "Trésorerie fin d'année"})):
            rows.append([lab.get(lang, lab["en"])] + [_num(x) for x in derived[key]])
        if not any(values.get(k) for k in ("cogs_by_year", "payroll_by_year", "opex_by_year")):
            rows = rows[:1]
        blocks.append(("h", _t("proj", lang)))
        blocks.append(("table", [""] + list(yrs), rows))
        be = derived.get("break_even_year")
        no_costs = not any(values.get(k) for k in ("cogs_by_year", "payroll_by_year", "opex_by_year"))
        if no_costs:
            blocks.append(("p", {"en": "No cost lines were given, so profit and break-even are not shown as results.", "fr": "Aucune charge n'a été indiquée : le résultat et le point mort ne sont pas présentés comme des résultats."}[lang if lang in ("en", "fr") else "en"]))
        else:
          blocks.append(("p", ({"en": f"Break-even is reached in {be}.", "fr": f"Le point mort est atteint en {be}."} if be else
                             {"en": "Break-even is not reached within the projection horizon.", "fr": "Le point mort n'est pas atteint sur l'horizon de projection."})[lang if lang in ("en", "fr") else "en"]))
        for a in derived.get("assumptions", []):
            blocks.append(("p", a))
        blocks.append(("chart",))
    if sid == "financial_projections" and not (derived and derived.get("revenue") and any(derived["revenue"])):
        missing.append({"en": "Revenue per year", "fr": "Chiffre d'affaires par année", "ar": "رقم المعاملات"}[lang if lang in ("en", "fr", "ar") else "en"])
    if missing:
        blocks.append(("h", _t("todo", lang)))
        blocks.append(("ul", [f"{m} {marker}" for m in missing]))
    return {"id": sid, "title": label(sec["title"], lang), "blocks": blocks, "missing": missing}


def compose_summary(values: dict, derived: dict | None, lang: str) -> list[tuple]:
    """A short summary built only from answers that exist."""
    name = values.get("project_name")
    parts: list[str] = []
    fr = lang == "fr"
    if name and values.get("sector"):
        parts.append((f"{name} : {values['sector']}." if fr else f"{name}: {values['sector']}."))
    elif name:
        parts.append(name + ".")
    if values.get("solution"):
        parts.append(str(values["solution"]).strip().rstrip(".") + ".")
    if values.get("target_customers"):
        parts.append((f"Clientèle visée : {values['target_customers']}." if fr else f"Target customers: {values['target_customers']}."))
    if values.get("total_investment"):
        extra = ""
        if values.get("funding_need_amount"):
            extra = (f" dont {_num(values['funding_need_amount'])} TND recherchés à l'extérieur" if fr else f", of which {_num(values['funding_need_amount'])} TND is sought externally")
        parts.append((f"Investissement total : {_num(values['total_investment'])} TND{extra}." if fr else f"Total investment: {_num(values['total_investment'])} TND{extra}."))
    if derived and derived.get("revenue") and any(derived["revenue"]):
        last = max(i for i, v in enumerate(derived["revenue"]) if v)
        parts.append((f"Chiffre d'affaires prévu en {derived['years'][last]} : {_num(derived['revenue'][last])} TND." if fr
                      else f"Revenue expected in {derived['years'][last]}: {_num(derived['revenue'][last])} TND."))
    return [("p", " ".join(parts))] if parts else []


def build_plan_docx(title: str, sections: list[dict], chart_png: bytes | None, lang: str, open_items: list[tuple[str, list[str]]]) -> bytes:
    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading(title or {"en": "Business plan", "fr": "Business plan", "ar": "خطة العمل"}[lang], 0)
    d.add_paragraph(_t("cover_sub", lang))
    p = d.add_paragraph()
    p.add_run(_t("banner", lang)).italic = True
    for sec in sections:
        d.add_heading(sec["title"], 1)
        for b in sec["blocks"]:
            kind = b[0]
            if kind == "h":
                d.add_heading(b[1], 2)
            elif kind == "p":
                _para_with_markers_text(d, b[1])
            elif kind == "ul":
                for item in b[1]:
                    _bullet(d, item)
            elif kind == "table":
                t = d.add_table(rows=1, cols=len(b[1]))
                t.style = "Light Grid Accent 1"
                for i, h in enumerate(b[1]):
                    t.rows[0].cells[i].text = h
                for r in b[2]:
                    cells = t.add_row().cells
                    for i, v in enumerate(r):
                        cells[i].text = str(v)
                d.add_paragraph()
            elif kind == "chart" and chart_png:
                d.add_picture(io.BytesIO(chart_png), width=Inches(6.0))
    if open_items:
        d.add_page_break()
        d.add_heading(_t("open", lang), 1)
        for sec_title, items in open_items:
            d.add_heading(sec_title, 2)
            for it in items:
                _bullet(d, it)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _bullet(d, text: str) -> None:
    p = d.add_paragraph(style="List Bullet")
    _fill_runs(p, text)


def _fill_runs(p, text: str) -> None:
    from docx.enum.text import WD_COLOR_INDEX

    from app.agents.writer import ANY_MARKER

    pos = 0
    for m in ANY_MARKER.finditer(text):
        p.add_run(text[pos:m.start()])
        r = p.add_run(m.group(0))
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW
        pos = m.end()
    p.add_run(text[pos:])


# ---------------------------------------------------------------------------- professional layer
ADVICE_H = {"en": "Advisor's notes", "fr": "Conseils", "ar": "ملاحظات المستشار"}
POLISH_NOTE = {"en": "Wording professionalised from your answers; no facts were added.",
               "fr": "Rédaction professionnalisée à partir de vos réponses ; aucun fait n'a été ajouté.",
               "ar": "صياغة مهنية انطلاقا من إجاباتكم دون إضافة وقائع."}


def advise(composed: dict, review, guidance_hits: list[dict], lang: str) -> None:
    """Append advisor notes: criteria the section does not cover yet, then the matching good practice. Works without a model."""
    from app.templates import label as _label

    notes: list[str] = []
    if review is not None:
        for c in review.criteria:
            if not c.met:
                notes.append(_label(c.text, lang) if isinstance(c.text, dict) else str(c.text))
    for g in guidance_hits[:1]:
        notes.append(f"{g['title']}. {g['text']}")
    if notes:
        composed["blocks"].append(("h", ADVICE_H.get(lang, ADVICE_H["en"])))
        composed["blocks"].append(("ul", notes[:5]))
        composed["advice"] = notes[:5]


def polish(composed: dict, sec: dict, values: dict, derived: dict | None, guidance_hits: list[dict], lang: str,
           llm, masker, trace) -> bool:
    """Replace the founder's raw text blocks with professional prose. Every figure is checked against the founder's facts."""
    import json

    from app import prompts
    from app.agents import writer as W
    from app.config import model_for
    from app.llm import LLMUnavailable

    raw_ids = [q for q in sec["questions"] if q in values and q in BANK_BY_ID and BANK_BY_ID[q].type in ("text", "longtext")]
    if not llm.available or not raw_ids:
        return False
    facts = {q: values[q] for q in sec["questions"] if q in values and q != "founders"}
    allowed = W.allowed_numbers(values, derived or {})
    p = prompts.load("plan_writer")
    adv = "\n".join(f"- {g['title']}: {g['text']}" for g in guidance_hits[:2])
    feedback = ""
    for attempt in (0, 1):
        user = prompts.render(p["text"], section=composed["title"], language={"fr": "French", "ar": "Arabic", "en": "English"}[lang],
                              guidance=adv, facts=masker.mask(json.dumps(facts, ensure_ascii=False)), feedback=feedback)
        with trace.step("plan_writer.llm" if attempt == 0 else "plan_writer.llm.retry", model=model_for("llm_main"), prompt_id=prompts.ref(p)):
            try:
                out = llm.chat_json(model=model_for("llm_main"), system="You write business-plan sections. Reply with JSON only.",
                                    user=user, schema=p.get("output_schema"), max_tokens=900)
            except LLMUnavailable as exc:
                trace.note(f"plan_writer skipped: {exc}")
                return False
        text = masker.unmask(str(out.get("text", ""))).strip()
        if not text:
            return False
        bad = W.unflagged_count(text, allowed)
        if bad and attempt == 0:
            feedback = f"\nYour previous draft contained {bad} figure(s) that are not in the facts. Remove them."
            continue
        text, _ = W.guard(text, allowed, lang)
        raw_labels = {_qlabel(q, lang) for q in raw_ids}
        kept, inserted = [], False
        i = 0
        blocks = composed["blocks"]
        while i < len(blocks):
            b = blocks[i]
            if b[0] == "h" and b[1] in raw_labels and i + 1 < len(blocks) and blocks[i + 1][0] == "p":
                if not inserted:
                    kept.append(("p", text))
                    kept.append(("p", POLISH_NOTE.get(lang, POLISH_NOTE["en"])))
                    inserted = True
                i += 2
                continue
            kept.append(b)
            i += 1
        composed["blocks"] = kept
        composed["polished"] = True
        return True
    return False
