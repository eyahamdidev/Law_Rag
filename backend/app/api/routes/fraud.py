"""Upload a document for a later fraud-signal review."""

from fastapi import APIRouter, File, Form, UploadFile

from app.modules.fraud.detector import analyze_upload
from app.schemas.fraud import FraudReport

router = APIRouter()


@router.post("/fraud/analyze", response_model=FraudReport)
async def analyze_fraud(
    file: UploadFile = File(...),
    document_type: str = Form(default="invoice"),
) -> FraudReport:
    content = await file.read()
    allowed = {"invoice", "bank_statement", "financing_application", "business_plan"}
    kind = document_type if document_type in allowed else "invoice"
    return analyze_upload(file.filename or "upload", content, kind)
