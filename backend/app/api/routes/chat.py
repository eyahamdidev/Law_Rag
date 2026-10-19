"""Founder messages: the single entry point n8n and the web app call."""

import base64

from fastapi import APIRouter, File, Form, Header, UploadFile

from app.modules.intake.extractor import inspect_document
from app.modules.orchestrator import profile as session_profile
from app.orchestrator.graph import run_turn
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_RAW_BYTES = 8 * 1024 * 1024


OFFICE = (".docx", ".xlsx", ".xls")


def _keep_raw(filename: str, mime: str) -> bool:
    """Files an agent may need as bytes: PDFs and images (fraud stamp check), Office plans (business plan)."""
    name, mime = filename.lower(), mime.lower()
    return mime == "application/pdf" or mime.startswith("image/") or name.endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp") + OFFICE)


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, x_session_id: str | None = Header(default=None)) -> ChatResponse:
    # The session can come in the body (web page) or the X-Session-Id header (business-plan page, n8n).
    session_id = body.session_id or x_session_id
    # Facts the founder states here pre-fill the business-plan questionnaire later.
    session_profile.merge(session_id, session_profile.hints_from_text(body.question))
    return run_turn(body.question.strip(), session_id=session_id,
                    legal_contract=body.legal_contract.model_dump(mode="json") if body.legal_contract else None)


@router.post("/chat/upload", response_model=ChatResponse)
async def chat_with_files(
    question: str = Form(...),
    session_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default_factory=list),
) -> ChatResponse:
    attachments, steps = [], []
    for upload in files[:3]:
        content = (await upload.read())[:MAX_UPLOAD_BYTES]
        attachment, step = inspect_document(upload.filename or "upload", content, upload.content_type or "")
        name = (upload.filename or "").lower()
        if name.endswith(OFFICE):
            # Binary Office files: decoding them as text gives noise. The business-plan service reads them.
            attachment.text, attachment.extraction = "", "none"
        if _keep_raw(name, upload.content_type or "") and len(content) <= MAX_RAW_BYTES:
            # Kept for agents that inspect the file itself (fraud stamp check, business-plan review).
            attachment.data_base64 = base64.b64encode(content).decode("ascii")
        attachments.append(attachment)
        steps.append(step)
    response = run_turn(question.strip(), session_id=session_id, attachments=attachments)
    response.trace = steps + response.trace
    return response
