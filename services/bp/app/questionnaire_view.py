"""What the UI needs: every question, its status and where its value came from."""

from __future__ import annotations

from app.profile import Context, merge_context
from app.questionnaire import BANK, describe
from app.templates import choose_template, load_template


def view(profile: dict | None, answers: dict | None, lang: str, template_id: str | None = None) -> dict:
    ctx: Context = merge_context(profile, answers, None)
    tid = choose_template(template_id, ctx.get("stage"))
    template = load_template(tid)
    feeds: dict[str, list[str]] = {}
    for sec in template["sections"]:
        for qid in sec["questions"]:
            feeds.setdefault(qid, []).append(sec["id"])
    questions = []
    for base in describe(lang):
        qid = base["id"]
        if qid in ctx.errors:
            status = "invalid"
        elif qid in ctx.values:
            status = "answered" if ctx.provenance[qid] == "questionnaire" else "prefilled"
        else:
            status = "missing"
        questions.append({
            **base, "status": status, "value": ctx.values.get(qid), "source": ctx.provenance.get(qid),
            "error": ctx.errors.get(qid), "feeds_sections": feeds.get(qid, []),
        })
    req = [q for q in questions if q["required"]]
    return {
        "template": {"id": tid, "title": template["title"], "verified_against_official_model": template["verified_against_official_model"]},
        "lang": lang,
        "progress": {
            "answered": sum(1 for q in questions if q["status"] in ("answered", "prefilled")),
            "total": len(questions),
            "required_done": sum(1 for q in req if q["status"] in ("answered", "prefilled")),
            "required_total": len(req),
        },
        "conflicts": ctx.conflicts,
        "ignored_keys": ctx.ignored_keys,
        "questions": questions,
    }
