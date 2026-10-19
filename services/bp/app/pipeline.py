"""The bp chain: parser -> reviewer -> financial checker -> writer (-> checker, one retry) -> chart.

One entry point, ``run``. Modes (spec section 6): ``review`` and ``draft_section``.

Inputs, any combination:
* ``file_ref``          an uploaded plan (docx, pdf, xlsx, txt)
* ``options.answers``   the guided questionnaire
* ``profile``           what the orchestrator already collected about the founder

All three are merged into one context before anything is judged. See profile.py
for precedence and conflict handling.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from app import financial as fin
from app import storage
from app.agents import chart_maker, claim_guard, guidance, reviewer, writer
from app.agents import critic as critic_agent
from app.agents import final_writer as final_writer_agent
from app.agents.common import Trace, fold
from app.config import model_for, settings
from app.contract import Artifact, Citation, Evidence, Handoff, ModuleError, Request, Response, Signal
from app.intake import Document, read_document
from app.llm import LLMClient
from app.masking import Masker, NoMasker
from app import plan_facts
from app.profile import Context, merge_context, missing_required
from app.questionnaire import BANK_BY_ID
from app.report import build_docx
from app.sections import answers_to_sections, combine
from app.agents import assessment
from app import benchmark_check, knowledge, plan_doc, prompts, template_detect
from app.templates import choose_template, label, load_template, section_index

SEV_ORDER = {"high": 0, "review": 1, "info": 2}

STATUTE_HINT = re.compile(r"\b(article|art\.|loi|décret|decret|code des|jort|circulaire|statut\w*|law|decree|statute)\b|المجلة|القانون|الفصل", re.I)
AID_HINT = re.compile(r"\b(bfpme|subvention|grant|prime|incitation|startup act|programme|programs?|éligib\w+|eligib\w+|bts|fonapram|sotugar)\b", re.I)

SUMMARY = {
    "en": "Review across {n} sections. {high} points need a close look, {review} are worth a second check. {missing}",
    "fr": "Revue sur {n} sections. {high} points demandent une vérification attentive, {review} méritent un second contrôle. {missing}",
    "ar": "مراجعة على {n} أقسام. {high} نقاط تستدعي مراجعة دقيقة و{review} تستحق تدقيقا ثانيا. {missing}",
}
MISSING_TXT = {
    "en": "Missing or weak sections: {names}.",
    "fr": "Sections manquantes ou faibles : {names}.",
    "ar": "أقسام ناقصة أو ضعيفة: {names}.",
}
SETTLE_TITLE = {"en": "Points to settle in your own answers", "fr": "Points à trancher dans vos propres réponses",
                "ar": "نقاط للحسم في إجاباتكم"}

# a role written after a name: "Aya - CEO", "Aya (CTO)", "Aya: finance"
_ROLE_SPLIT = re.compile(r"\s+[-–—]\s+|\s*[(:]\s*")


def _opt(req: Request) -> dict:
    return dict(req.options or {})


def _sig(kind: str, severity: str, message: str, field: str, value: Any = None, source: str = "rule", tag: str = "") -> Signal:
    return Signal(id=f"bp-{kind}{('-' + tag) if tag else ''}", kind=kind, severity=severity, message=message,
                  evidence=Evidence(field=field, value=value), source=source)


def _detect_handoff(req: Request) -> Handoff | None:
    q = (req.question or "").strip()
    if not q:
        return None
    # A statute question wins: the aid module also hands those on to law, so go straight there.
    if STATUTE_HINT.search(q):
        return Handoff(to="law", question=q)
    if AID_HINT.search(q):
        return Handoff(to="aid", question=q)
    return None


def _doc_conflicts(doc_model: fin.FinancialModel, q_model: fin.FinancialModel) -> list[Signal]:
    """The plan and the questionnaire disagree on a figure. The plan's figure is used; say so."""
    out = []
    if doc_model.origin == "none" or q_model.origin == "none":
        return out
    for name in ("revenue", "payroll", "cogs", "opex", "capex"):
        a, b = getattr(doc_model, name), getattr(q_model, name)
        for t, (x, y) in enumerate(zip(a, b)):
            if x is not None and y is not None and abs(x - y) > max(1.0, 0.01 * max(abs(x), abs(y))):
                yr = doc_model.years[t] if t < len(doc_model.years) else f"Y{t + 1}"
                out.append(_sig("source_conflict", "review",
                                f"Review this: {name} for {yr} is {x:,.0f} in the uploaded plan and {y:,.0f} in the questionnaire. The plan's figure was used.",
                                f"{name}[{yr}]", x, tag=f"{name}-{t}"))
    for name, qa in (("total_investment", q_model.total_investment), ("loan_principal", q_model.loan_principal), ("own_funds", q_model.own_funds)):
        da = getattr(doc_model, name, None)
        if name == "total_investment":
            da = doc_model.uses_total_stated or (sum(doc_model.uses.values()) or None)
        if da is not None and qa is not None and abs(da - qa) > max(1.0, 0.01 * max(abs(da), abs(qa))):
            out.append(_sig("source_conflict", "review",
                            f"Review this: {name.replace('_', ' ')} is {da:,.0f} in the uploaded plan and {qa:,.0f} in the questionnaire. The plan's figure was used.",
                            name, da, tag=name))
    return out


def _profile_signals(ctx: Context, model: fin.FinancialModel) -> list[Signal]:
    out = []
    for c in ctx.conflicts:
        vals = ", ".join(f"{s}: {v}" for s, v in c["values"].items())
        out.append(_sig("profile_conflict", "review",
                        f"Review this: '{c['field']}' differs between sources ({vals}). The {c['chosen_source']} value was used.",
                        c["field"], c["values"].get(c["chosen_source"]), tag=c["field"]))
    # the orchestrator may know the amount the founder is looking for
    need = ctx.get("funding_need_amount")
    external = sum(x for x in ((model.loan_principal or 0), (model.grant or 0)))
    if need and external and abs(need - external) > max(1.0, 0.05 * max(need, external)) and ctx.provenance.get("funding_need_amount") != "questionnaire":
        out.append(_sig("profile_conflict", "review",
                        f"Review this: the funding need collected earlier is {need:,.0f} but loans plus grants in the plan add up to {external:,.0f}.",
                        "funding_need_amount", need, tag="funding-need"))
    for qid, msg in ctx.errors.items():
        out.append(_sig("answer_invalid", "review", f"Review this: the answer to '{qid}' could not be used ({msg}).", qid, tag=qid))
    for key in ctx.ignored_keys:
        out.append(_sig("answer_ignored", "info", f"Review this: '{key}' is not a questionnaire field and was ignored.", key, tag=key))
    return out


def _summary(lang: str, score: int, n: int, signals: list[Signal], weak: list[str]) -> str:
    lang = lang if lang in SUMMARY else "en"
    miss = MISSING_TXT[lang].format(names=", ".join(weak[:6])) if weak else ""
    return SUMMARY[lang].format(n=n, high=sum(s.severity == "high" for s in signals),
                                review=sum(s.severity == "review" for s in signals), missing=miss).strip()


def run(req: Request, llm: LLMClient | None = None) -> Response:
    t0 = time.perf_counter()
    opt = _opt(req)
    mode = opt.get("mode", "review")
    if mode not in ("review", "draft_section"):
        raise ModuleError("BAD_INPUT", "options.mode must be 'review' or 'draft_section'.")
    fw_mode = opt.get("final_writer_mode", "batch")
    if fw_mode not in ("batch", "sequential"):
        raise ModuleError("BAD_INPUT", "options.final_writer_mode must be 'batch' or 'sequential'.")
    try:
        fw_seed = int(opt.get("seed", final_writer_agent.SEED))
    except (TypeError, ValueError):
        raise ModuleError("BAD_INPUT", "options.seed must be an integer.")
    lang = req.lang if req.lang in ("fr", "ar", "en") else "fr"
    doc_lang: str | None = None
    deadline = time.monotonic() + settings.timeout_budget_s
    llm = llm or LLMClient(deadline=deadline)
    if llm.deadline is None:
        llm.deadline = deadline
    use_llm = opt.get("llm", True) and llm.available
    trace = Trace()
    answers = opt.get("answers")
    if answers is not None and not isinstance(answers, dict):
        raise ModuleError("BAD_INPUT", "options.answers must be an object of question id to answer.")
    if not (req.file_ref or answers or req.profile):
        return Response(request_id=req.request_id, status="abstain",
                        answer={"en": "Upload a business plan or answer the questionnaire so there is something to review.",
                                "fr": "Téléversez un business plan ou répondez au questionnaire pour lancer la revue.",
                                "ar": "ارفعوا خطة العمل أو أجيبوا على الاستبيان لبدء المراجعة."}[lang],
                        signals=[_sig("missing_input", "info", "Review this: no plan, no answers and no profile were provided.", "input")],
                        handoff=_detect_handoff(req))

    # ---- inputs -----------------------------------------------------------------
    doc: Document | None = None
    with trace.step("intake"):
        if req.file_ref:
            doc = read_document(storage.read(req.file_ref))
    if doc is not None and opt.get("detect_lang", True):
        from app.lang_detect import detect_document_lang

        doc_lang = detect_document_lang(doc.text, default=lang)
        if doc_lang != lang:
            trace.note(f"document language looks like {doc_lang}; UI lang stays {lang}")
    ctx0 = merge_context(req.profile, answers, None)
    heads = [b.text for b in doc.blocks if b.kind == "heading"] if doc is not None else None
    template_id = choose_template(opt.get("template"), ctx0.get("stage"), heads)
    template = load_template(template_id)
    idx = section_index(template)

    masking_on = bool(opt.get("masking", True))
    masker: Masker = Masker(names=_names(ctx0)) if masking_on else NoMasker()
    from app.agents import parser as parser_agent

    plan = parser_agent.ParsedPlan()
    if doc is not None:
        content_lang = doc_lang or lang
        plan = parser_agent.parse(doc, template, llm=llm if (use_llm and settings.llm_step("parser")) else LLMClient(api_key="", cache=False), masker=masker, lang=content_lang,
                                  trace=trace, mode=opt.get("parser_mode", "auto"))
        if plan.model.origin == "none" and doc.scanned_pages and use_llm and settings.llm_step("vision"):
            rows = chart_maker.read_charts(doc, llm, trace)
            if rows:
                plan.warnings.append(f"A vision model read {len(rows)} table rows from scanned pages. They were NOT used in checks. Check them by hand.")
    ctx = merge_context(req.profile, answers, plan.facts)
    _pf, _pf_extra = plan_facts.validate_context(ctx)
    ctx.errors.update(_pf_extra)
    if masking_on and doc is not None:
        # Names that only appear inside the uploaded plan were unknown when the first masker was built, so they would
        # have gone to the model in clear text. Rebuild it from the merged context for every later step.
        masker = Masker(names=_names(ctx))

    # ---- merge sections from both input methods ---------------------------------------
    q_sections = answers_to_sections(template, ctx.values, ctx.provenance, lang)
    sections = combine(plan.sections, q_sections)

    # ---- financial model -----------------------------------------------------------
    q_model = fin.from_answers(ctx.values)
    model = fin.merge_models(plan.model, q_model)
    model.headcount = model.headcount or ctx.get("headcount")
    model.avg_gross_salary = model.avg_gross_salary or ctx.get("avg_gross_salary")
    derived = fin.derive(model) if (model.has_projection() or model.loan_principal) else None
    signals: list[Signal] = []
    with trace.step("financial_checker"):
        if derived is not None or model.uses or model.sources:
            signals += fin.check(model, derived, early_stage=(template_id == "investor_pitch"))
        signals += _doc_conflicts(plan.model, q_model)
    signals += _profile_signals(ctx, model)
    with trace.step("benchmarks"):
        bench_signals, bench_report = benchmark_check.run(model, derived, ctx.values)
    signals += bench_signals

    # ---- review ------------------------------------------------------------------
    with trace.step("reviewer.total"):
        reviews = reviewer.review_all(template, sections, lang=lang, llm=llm, masker=masker, trace=trace,
                                      style=opt.get("rubric_style", "plain"), use_llm=use_llm and settings.llm_step("reviewer"))
    for rv in reviews:
        if rv.status == "missing" and rv.required:
            signals.append(Signal(id=f"bp-section-{rv.section_id}", kind="section_missing", severity="review",
                                  message=f"Review this: nothing was found for the section '{rv.title}'.",
                                  evidence=Evidence(field=rv.section_id), source="rule"))
        elif rv.status == "weak" and rv.required:
            unmet = [c.text for c in rv.criteria if not c.met][:3]
            signals.append(Signal(id=f"bp-section-{rv.section_id}", kind="section_weak", severity="info",
                                  message=f"Review this: the section '{rv.title}' scores {rv.score}/100. Not yet covered: {'; '.join(unmet)}.",
                                  evidence=Evidence(field=rv.section_id, page=rv.page, bbox=rv.bbox),
                                  source="model" if rv.method == "model" else "rule"))
    miss_req = missing_required(ctx, extra_present=set(plan.facts))
    if miss_req and not req.file_ref:
        signals.append(_sig("missing_info", "info", "Review this: questions still open that a full draft needs: " + ", ".join(miss_req) + ".",
                            "questionnaire", miss_req, tag="required"))

    # ---- credibility -----------------------------------------------------------------
    assess: assessment.Assessment | None = None
    full_text = doc.text if doc is not None else "\n".join(v.get("text", "") for v in sections.values())
    if doc is not None and len(full_text.strip()) >= 200:  # the verdict judges a document, not a short questionnaire
        with trace.step("assessment"):
            req_rv = [r for r in reviews if r.required] or reviews
            fin_sigs = [s for s in signals if s.kind in assessment.FIN_INTEGRITY]
            structure = {
                "missing_ratio": sum(r.status == "missing" for r in req_rv) / max(1, len(req_rv)),
                "complete_ratio": sum(r.status == "complete" for r in req_rv) / max(1, len(req_rv)),
                "fin_high": sum(s.severity == "high" for s in fin_sigs), "fin_review": sum(s.severity == "review" for s in fin_sigs),
                "has_financials": derived is not None and any(derived["revenue"]),
                "expects_financials": any(r.section_id in ("financial_projections", "financials_ask") for r in reviews),
            }
            assess = assessment.assess(full_text, {k: v.get("text", "") for k, v in sections.items()}, lang=lang,
                                       llm=llm, masker=masker, trace=trace, use_llm=use_llm and settings.llm_step("assessment"), structure=structure)
        for f in assess.flags:
            if f.group == "strength":
                continue
            signals.append(Signal(id=f"bp-flag-{f.rule}", kind="credibility_flag" if f.group == "fraud" else "plan_weakness",
                                  severity="high" if f.group == "fraud" and f.weight >= 2 else "review",
                                  message=f"Review this: {f.why}", evidence=Evidence(field=f.rule, value=f.quote),
                                  source="model" if f.source == "model" else "rule"))

    tpl = template_detect.scan(doc.text) if doc is not None else {"unfilled": False}
    if tpl["unfilled"]:
        if assess is not None:
            assess.verdict, assess.score, assess.strengths, assess.strength_count = "unfilled", 0, [], 0
            assess.rationale = {"en": f"{tpl['total']} template placeholders found ({', '.join(tpl['examples'])}). Section scores are not meaningful until the template is filled in.",
                                "fr": f"{tpl['total']} éléments de modèle trouvés ({', '.join(tpl['examples'])}). Les scores par section n'ont pas de sens tant que le modèle n'est pas rempli.",
                                "ar": f"{tpl['total']} عنصر نموذج. درجات الأقسام بلا معنى قبل ملء النموذج."}.get(lang, "")
        signals.append(_sig("unfilled_template", "high",
                            f"Review this: this file looks like an unfilled template ({tpl['total']} placeholders such as {', '.join(repr(e) for e in tpl['examples'][:3])}). "
                            "The help text and sample names or figures inside it are not your plan. Fill it in, then upload it again.", "document", tpl["kinds"]))

    # ---- drafts ---------------------------------------------------------------------
    drafts: list[writer.Draft] = []
    citations: list[Citation] = []
    wanted: list[str] = []
    if mode == "draft_section":
        sid = opt.get("section_id")
        if sid in ("all", "missing"):
            wanted = [r.section_id for r in reviews if r.status in ("missing", "weak")]
        elif sid in idx:
            wanted = [sid]
        else:
            raise ModuleError("BAD_INPUT", f"options.section_id must be a template section id or 'missing'. Known: {', '.join(idx)}")
    elif opt.get("draft_missing"):
        wanted = [r.section_id for r in reviews if r.status in ("missing", "weak") and r.required]
    for sid in wanted:
        sec = idx[sid]
        existing = sections.get(sid, {}).get("text", "")
        hits = guidance.retrieve(sid, f"{label(sec['title'], 'en')} {existing[:200]}", k=2)
        hits += knowledge.search(f"{label(sec['title'], lang)} {ctx.get('sector') or ''} {existing[:150]}", k=1)
        with trace.step(f"writer.{sid}"):
            d = writer.draft_section(sec, values=ctx.values, derived=derived, existing=existing, guidance=hits, lang=lang,
                                     llm=llm if (use_llm and settings.llm_step("drafts")) else LLMClient(api_key="", cache=False), masker=masker, trace=trace,
                                     extra_numbers=_plan_numbers(plan))
        drafts.append(d)
        for h in hits:
            citations.append(Citation(doc_id=h.get("doc_id", "bp-guidance"), passage_id=h["id"], code_or_title=h["title"], score=float(h.get("score", 0)),
                                      score_kind="relevance"))
        if d.flagged:
            signals.append(Signal(id=f"bp-draft-{sid}", kind="figures_to_confirm", severity="review",
                                  message=f"Review this: the draft of '{d.title}' contains {len(d.flagged)} figure(s) that are not in your inputs. They are marked for you to confirm.",
                                  evidence=Evidence(field=sid, value=[f["value"] for f in d.flagged][:8]), source="rule"))

    signals.sort(key=lambda s: (SEV_ORDER[s.severity], s.id))
    if not llm.available and opt.get("llm", True):
        signals.append(_sig("llm_unavailable", "info",
                            "Review this: no language model was reachable, so section scoring used the keyword rubric and drafts use your answers only. Financial checks are unaffected.",
                            "llm", source="rule"))

    # ---- artifacts ------------------------------------------------------------------
    score = reviewer.overall(reviews)
    weak_names = [r.title for r in reviews if r.status in ("missing", "weak") and r.required]
    summary = _summary(lang, score, len(reviews), signals, weak_names)
    if tpl["unfilled"] and assess is not None:
        summary = assessment.LABEL_TEXT["unfilled"][lang if lang in ("en", "fr", "ar") else "en"] + ". " + assess.rationale
    elif assess is not None:
        summary = f"{assessment.LABEL_TEXT[assess.verdict][lang if lang in ('en', 'fr', 'ar') else 'en']}. " + summary
    report = {
        "contract": "bp_report/1",
        "mode": mode,
        "template": {"id": template_id, "title": template["title"], "verified_against_official_model": template["verified_against_official_model"]},
        "input": {
            "methods": [m for m, on in (("upload", bool(req.file_ref)), ("questionnaire", bool(answers)), ("orchestrator_profile", bool(req.profile))) if on],
            "document": None if doc is None else {"kind": doc.kind, "pages": doc.page_count, "warnings": plan.warnings, "scanned_pages": doc.scanned_pages},
        },
        "context": {"values": ctx.values, "provenance": ctx.provenance,
                    "provenance_labels": plan_facts.PlanFacts.from_context(ctx).labelled_provenance(),
                    "conflicts": ctx.conflicts,
                    "missing_required": miss_req, "answer_errors": ctx.errors, "ignored_keys": ctx.ignored_keys, "sources_used": ctx.sources_used},
        "assessment": None if assess is None else {**assess.to_dict(), "label": assessment.LABEL_TEXT[assess.verdict]},
        "benchmarks": bench_report,
        "completeness": {"overall": score, "sections": [r.to_dict() for r in reviews]},
        "financials": None if derived is None else {**_jsonable(derived), "origin": model.origin},
        "drafts": [d.to_dict() for d in drafts],
        "unmapped": plan.unmapped,
        "signals": [s.model_dump() for s in signals],
        "privacy": {"masking": not isinstance(masker, NoMasker), "masked_counts": masker.report(), "model_used": bool(llm.usage.calls or llm.usage.cache_hits)},
        "usage": llm.usage.as_dict(),
        "summary_text": summary,
    }
    artifacts: list[Artifact] = []
    chart_png = None
    if derived is not None and any(derived["revenue"]):
        with trace.step("chart_maker"):
            try:
                chart_png = chart_maker.projection_png(derived, lang, currency=str(ctx.values.get("currency") or "TND"))
            except Exception as exc:  # noqa: BLE001  a broken plotting install must not lose the review
                chart_png = None
                trace.note(f"chart skipped: {exc.__class__.__name__}: {exc}")
        if chart_png:
            artifacts.append(Artifact(kind="png", file_ref=storage.put(chart_png), label="projection_chart"))
    if opt.get("generate_plan") and mode == "review":
        with trace.step("critic"):
            crit = critic_agent.critique(full_text, sections, reviews, lang=lang, llm=llm, masker=masker, trace=trace,
                                         use_llm=use_llm and settings.llm_step("critic"), values=ctx.values, derived=derived)
        final_plan = None
        settle = ""
        with trace.step("plan_document"):
            rv_by = {r.section_id: r for r in reviews}
            exec_id = "executive_summary"
            comps: dict[str, dict] = {}
            min_polish_s = 12.0
            for sec in template["sections"]:
                if sec["id"] == exec_id:
                    continue
                comp = plan_doc.compose_section(sec, ctx.values, derived, lang)
                hits = guidance.retrieve(sec["id"], label(sec["title"], "en"), k=2)
                if use_llm and settings.llm_step("plan_writer") and (deadline - time.monotonic()) > min_polish_s:
                    plan_doc.polish(comp, sec, ctx.values, derived, hits, lang, llm, masker, trace)
                ctx_text = plan_doc.critic_context(sec["id"], sections, comp, full_text)
                plan_doc.advise(comp, rv_by.get(sec["id"]), hits, lang, critic_notes=crit.notes_for(sec["id"], ctx_text))
                comps[sec["id"]] = comp
            exec_sec = idx[exec_id]
            exec_comp = plan_doc.compose_section(exec_sec, ctx.values, derived, lang)
            plan_doc.build_executive_summary(exec_comp, exec_sec, ctx.values, derived, lang)
            hits = guidance.retrieve(exec_id, label(exec_sec["title"], "en"), k=2)
            if use_llm and settings.llm_step("plan_writer") and (deadline - time.monotonic()) > min_polish_s:
                plan_doc.polish(exec_comp, exec_sec, ctx.values, derived, hits, lang, llm, masker, trace)
            exec_ctx = plan_doc.critic_context(exec_id, sections, exec_comp, full_text)
            plan_doc.advise(exec_comp, rv_by.get(exec_id), hits, lang, critic_notes=crit.notes_for(exec_id, exec_ctx))
            comps[exec_id] = exec_comp
            secs = [comps[s["id"]] for s in template["sections"]]
            open_items = [(s_["title"], s_["missing"]) for s_ in secs if s_["missing"]]
            settle = plan_doc.consistency_notes(ctx.values, lang)
            if settle:
                open_items.append((SETTLE_TITLE.get(lang, SETTLE_TITLE["en"]), settle))
            plan_bytes = plan_doc.build_plan_docx(str(ctx.get("project_name") or ""), secs, chart_png, lang, open_items,
                                                  critique=crit.to_dict(), final_plan=None)
        artifacts.append(Artifact(kind="docx", file_ref=storage.put(plan_bytes), label="business_plan"))
        # Chat builds prioritise the Word file (plan_writer sections). Institutional rewrite runs only if time remains.
        chat_build = bool(opt.get("chat_build"))
        run_final = use_llm and settings.llm_step("final_writer") and not chat_build
        if chat_build and use_llm and settings.llm_step("final_writer") and (deadline - time.monotonic()) > 90:
            run_final = True
        if run_final:
            with trace.step("final_writer"):
                final_plan = _final_plan(masker, ctx.values, derived, full_text, crit, deadline, mode=fw_mode, seed=fw_seed)
            if final_plan is not None:
                report["final_plan"] = final_plan
                if plan_doc._usable_narrative(final_plan):
                    plan_bytes = plan_doc.build_plan_docx(str(ctx.get("project_name") or ""), secs, chart_png, lang, open_items,
                                                          critique=crit.to_dict(), final_plan=final_plan)
                    artifacts[-1] = Artifact(kind="docx", file_ref=storage.put(plan_bytes), label="business_plan")
        report["critique"] = crit.to_dict()
        report["generated_plan"] = {"sections": [{"id": s_["id"], "title": s_["title"], "missing": s_["missing"], "polished": bool(s_.get("polished")),
                                                  "claims_removed": s_.get("claims_removed", []), "advice": s_.get("advice", [])} for s_ in secs],
                                    "open_items": sum(len(s_["missing"]) for s_ in secs), "consistency_notes": settle}
    with trace.step("report.docx"):
        artifacts.append(Artifact(kind="docx", file_ref=storage.put(build_docx(report, chart_png, lang)), label="bp_review" if mode == "review" else "bp_draft"))
    artifacts.append(Artifact(kind="json", file_ref=storage.put(json.dumps(report, ensure_ascii=False, default=str).encode()), label="bp_report"))

    answer = summary
    if mode == "draft_section" and drafts:
        answer = "\n\n".join(f"## {d.title}\n{d.text}" for d in drafts)
    return Response(request_id=req.request_id, status="ok", answer=answer, citations=citations, signals=signals, artifacts=artifacts,
                    handoff=_detect_handoff(req), trace=trace.steps, latency_ms=int((time.perf_counter() - t0) * 1000))


def _plan_numbers(plan) -> set[float]:
    return writer.allowed_numbers([s["text"] for s in plan.sections.values()], plan.facts)


def _final_plan(masker: Masker, values: dict, derived: dict | None, plan_text: str, crit, deadline: float,
                mode: str = "batch", seed: int = final_writer_agent.SEED) -> dict | None:
    """The institutional six-section rewrite. Names stay local: inputs are masked, the result is unmasked.

    The founders' answer is part of the facts (masked, so the model never sees a real name): without it the model
    invents a team. Every section then goes through the claim guard, which replaces what the inputs do not support
    by [NEEDED: ...] placeholders. Degrades to None on any failure, so the plan document and the rest of the report
    are never lost.
    """
    facts = json.dumps({"answers": dict(values), "derived": writer._slim(derived)}, ensure_ascii=False, default=str)
    try:
        out = asyncio.run(final_writer_agent.run_final_writer_agent(
            prompts, masker.mask(facts), masker.mask(plan_text),
            masker.mask(json.dumps(crit.to_dict()["weaknesses"], ensure_ascii=False)), deadline=deadline, mode=mode,
            seed=seed))
        out = masker.unmask_obj(out)
    except Exception:  # noqa: BLE001  a broken final writer must not lose the plan document
        return None
    try:
        return _guard_final_plan(out, values, plan_text)
    except Exception:  # noqa: BLE001  the guard must never lose the plan either; an unguarded plan is flagged as such
        out["guard"] = "failed"
        return out


def _guard_final_plan(out: dict, values: dict, plan_text: str) -> dict:
    evidence = claim_guard.build_evidence(values, extra_text=plan_text)
    marker = writer.MARKERS["en"]
    needed: list[str] = []
    removed_total = 0
    for s in out.get("sections", []):
        text = s.get("text") or ""
        if not text:
            continue
        clean, issues = claim_guard.sanitize(text, evidence, currency=str(values.get("currency") or "TND"), marker=marker, lang="en")
        s["text"] = clean
        s["claims_removed"] = issues
        removed_total += len(issues)
        for item in claim_guard.needed_items(clean):
            if item not in needed:
                needed.append(item)
    for item in out.get("open_items") or []:
        item = str(item).strip()
        if item and item not in needed:
            needed.append(item)
    out["open_items"] = needed
    out["guard"] = {"claims_replaced": removed_total}
    return out


def _names(ctx: Context) -> list[str]:
    """Names to hide from the model: the project, and each founder's NAME (not the role written after it)."""
    names: list[str] = []
    project = str(ctx.get("project_name") or "").strip()
    if project:
        names.append(project)
    founders = ctx.get("founders")
    if founders:
        for chunk in re.split(r"[,;\n]", str(founders)):
            who = _ROLE_SPLIT.split(chunk.strip(), maxsplit=1)[0].strip(" .")
            if len(who) >= 3 and who.lower() != project.lower() and who not in names:
                names.append(who)
    return names


def _jsonable(d: dict) -> dict:
    return json.loads(json.dumps(d, default=str))
