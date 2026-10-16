"""Founder messages: the single entry point n8n and the web app call."""

import base64

from fastapi import APIRouter, File, Form, UploadFile

from app.modules.intake.extractor import inspect_document
from app.orchestrator.graph import run_turn
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_RAW_BYTES = 8 * 1024 * 1024


def _is_pdf_or_image(filename: str, mime: str) -> bool:
    name, mime = filename.lower(), mime.lower()
    return mime == "application/pdf" or mime.startswith("image/") or name.endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp"))


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    return run_turn(body.question.strip(), session_id=body.session_id,
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
        if _is_pdf_or_image(upload.filename or "", upload.content_type or "") and len(content) <= MAX_RAW_BYTES:
            # Kept for agents that inspect the file itself (fraud stamp and signature check).
            attachment.data_base64 = base64.b64encode(content).decode("ascii")
        attachments.append(attachment)
        steps.append(step)
    response = run_turn(question.strip(), session_id=session_id, attachments=attachments)
    response.trace = steps + response.trace
    return response
