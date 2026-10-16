"""Turn questionnaire answers into section text, so both input methods feed the same reviewer."""

from __future__ import annotations

from app.agents.writer import _render_value
from app.questionnaire import BANK_BY_ID


def answers_to_sections(template: dict, values: dict, provenance: dict, lang: str) -> dict[str, dict]:
    """Only answers given by the founder in the questionnaire (or supplied by the orchestrator) become text.

    Document facts are not echoed back into the plan text.
    """
    out: dict[str, dict] = {}
    for sec in template["sections"]:
        lines = []
        for qid in sec["questions"]:
            if qid not in values or provenance.get(qid) == "document":
                continue
            q = BANK_BY_ID[qid]
            lab = {"en": q.en, "fr": q.fr, "ar": q.ar}.get(lang, q.en)
            lines.append(f"{lab}: {_render_value(qid, values[qid], None)}.")
        if lines:
            out[sec["id"]] = {"text": "\n".join(lines), "segments": [{"heading": "questionnaire", "page": None, "bbox": None}],
                              "confidence": 1.0, "method": "questionnaire", "sources": ["questionnaire"]}
    return out


def combine(doc_sections: dict[str, dict], q_sections: dict[str, dict]) -> dict[str, dict]:
    """The plan's own text comes first. Questionnaire lines are appended so a thin section can be completed by answers."""
    out: dict[str, dict] = {}
    for sid in set(doc_sections) | set(q_sections):
        d, q = doc_sections.get(sid), q_sections.get(sid)
        if d and q:
            out[sid] = {**d, "text": d["text"] + "\n" + q["text"], "sources": ["document", "questionnaire"]}
        elif d:
            out[sid] = {**d, "sources": ["document"]}
        else:
            out[sid] = q
    return out
