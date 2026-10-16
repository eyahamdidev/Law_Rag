"""Founder messages: the single entry point n8n and the web app call."""

from fastapi import APIRouter, File, Form, UploadFile

from app.modules.intake.extractor import inspect_document
from app.orchestrator.graph import run_turn
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


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
        attachments.append(attachment)
        steps.append(step)
    response = run_turn(question.strip(), session_id=session_id, attachments=attachments)
    response.trace = steps + response.trace
    return response
