"""Business plan: guided questionnaire and plan upload, both through the bp service."""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.modules.bp import client
from app.modules.orchestrator import profile as session_profile

router = APIRouter()

MAX_UPLOAD = 25 * 1024 * 1024


def _json_field(raw: str | None, name: str) -> dict:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(422, f"{name} must be a JSON object") from exc
    if not isinstance(val, dict):
        raise HTTPException(422, f"{name} must be a JSON object")
    return val


def _lang(lang: str) -> str:
    return lang if lang in ("fr", "ar", "en") else "fr"


@router.post("/bp/questionnaire")
def bp_questionnaire(
    body: dict,
    x_session_id: str | None = Header(default=None),
):
    """Questions with their status. Anything the orchestrator already knows is returned as 'prefilled'."""
    profile = {**session_profile.get(x_session_id), **(body.get("profile") or {})}
    try:
        status, data = client.questionnaire(lang=_lang(body.get("lang", "fr")), profile=profile,
                                            answers=body.get("answers") or {}, template=body.get("template"))
    except client.BpUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    if status >= 400:
        raise HTTPException(status, data)
    return data


@router.post("/bp/chat")
def bp_chat(body: dict, x_session_id: str | None = Header(default=None)):
    """One turn of the chat-style questionnaire. The client sends back the state it got last time."""
    profile = {**session_profile.get(x_session_id), **(body.get("profile") or {})}
    try:
        status, data = client.chat(lang=_lang(body.get("lang", "fr")), profile=profile, state=body.get("state"),
                                   message=body.get("message"), action=body.get("action"))
    except client.BpUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    if status >= 400:
        raise HTTPException(status, data)
    return data


@router.post("/bp/run")
async def bp_run(
    mode: str = Form(default="review"),
    lang: str = Form(default="fr"),
    answers: str | None = Form(default=None),
    profile: str | None = Form(default=None),
    section_id: str | None = Form(default=None),
    template: str | None = Form(default=None),
    question: str | None = Form(default=None),
    draft_missing: bool = Form(default=False),
    generate_plan: bool = Form(default=False),
    chat_build: bool = Form(default=False),
    seed: int | None = Form(default=None),
    ignore_profile: bool = Form(default=False),
    file: UploadFile | None = File(default=None),
    x_session_id: str | None = Header(default=None),
):
    """Review or draft. Send a file, answers, or both. The session profile is added automatically."""
    file_ref = None
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "File is larger than 25 MB.")
        if data:
            file_ref = client.store_upload(data)
    ans = _json_field(answers, "answers")
    base_profile = {} if (ignore_profile or (file_ref and not ans)) else session_profile.get(x_session_id)  # an uploaded plan is judged on its own text
    merged_profile = {**base_profile, **_json_field(profile, "profile")}
    options = {"mode": mode, "answers": ans or None, "section_id": section_id, "template": template, "draft_missing": draft_missing,
               "generate_plan": generate_plan or None, "chat_build": chat_build or None, "seed": seed}
    options = {k: v for k, v in options.items() if v not in (None, "")}
    try:
        status, resp = client.run(lang=_lang(lang), file_ref=file_ref, profile=merged_profile, options=options, question=question)
    except client.BpUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    if resp.get("status") == "error":
        err = resp.get("error", {})
        raise HTTPException(status, {"code": err.get("code"), "message": err.get("message")})
    report = None
    for art in resp.get("artifacts", []):
        if art.get("label") == "bp_report":
            report = client.read_artifact_json(art["file_ref"])
            if report is None:
                raise HTTPException(500, "The business-plan service made a report but the gateway cannot read it. "
                                         "Both must use the same uploads folder: set UPLOADS_DIR to the same path for both.")
    # keep what the founder confirmed in the questionnaire, so the next tab sees it too
    if ans and report:
        confirmed = {k: v for k, v in report["context"]["values"].items() if report["context"]["provenance"].get(k) == "questionnaire"
                     and k in ("stage", "sector", "legal_form", "startup_label", "governorate", "export_status", "headcount", "avg_gross_salary", "funding_instrument")}
        session_profile.merge(x_session_id, confirmed)
    return {"response": resp, "report": report}


@router.get("/files/{ref}")
def get_file(ref: str, kind: str = "docx", name: str = "business-plan"):
    """Download an artifact the bp service produced. The reference is a sha256, never a path."""
    path = client.artifact_path(ref)
    if path is None:
        raise HTTPException(404, "Unknown file")
    safe = "".join(c for c in name if c.isalnum() or c in "-_")[:60] or "file"
    return FileResponse(path, media_type=client.content_type(kind), filename=f"{safe}.{kind}")


@router.delete("/profile")
def forget_profile(x_session_id: str | None = Header(default=None)):
    session_profile.clear(x_session_id)
    return {"profile": {}}


@router.get("/profile")
def read_profile(x_session_id: str | None = Header(default=None)):
    return {"profile": session_profile.get(x_session_id)}


@router.put("/profile")
def update_profile(body: dict, x_session_id: str | None = Header(default=None)):
    if not x_session_id:
        raise HTTPException(400, "X-Session-Id header is required")
    return {"profile": session_profile.merge(x_session_id, body)}
