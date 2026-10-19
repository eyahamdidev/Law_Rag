"""Fraud tab: stamp verification or payment scoring via fraud_detection."""

import re

import httpx
from fastapi import APIRouter, File, Form, Header, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.modules.fraud.detector import analyze_upload, decide_enrollment
from app.modules.fraud.gallery import list_saved_stamps
from app.schemas.fraud import FraudDecideResult, FraudReport, FraudStampGallery, FraudStampSpecimen

router = APIRouter()


def _browser_entity(session_id: str | None) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "", session_id or "")[:32].lower()
    return f"browser-{token or 'anonymous'}"


class FraudDecideRequest(BaseModel):
    proposal_id: str = Field(min_length=8, max_length=80)
    approve: bool
    tenant_secret: str | None = None


@router.post("/fraud/analyze", response_model=FraudReport)
async def analyze_fraud(
    file: UploadFile = File(...),
    mode: str = Form(default="stamp"),
    entity_id: str = Form(default=""),
    tenant_secret: str = Form(default=""),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> FraudReport:
    content = await file.read()
    kind = mode if mode in {"stamp", "payment"} else "stamp"
    org = entity_id.strip() or None
    if kind == "stamp" and not org:
        org = _browser_entity(x_session_id)
    secret = tenant_secret.strip() or None
    return analyze_upload(file.filename or "upload", content, kind, org, secret)


@router.get("/fraud/stamps", response_model=FraudStampGallery)
async def fraud_stamp_gallery(
    tenant_secret: str = "",
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    x_fraud_tenant_secret: str | None = Header(default=None, alias="X-Fraud-Tenant-Secret"),
) -> FraudStampGallery:
    entity = _browser_entity(x_session_id)
    secret = (x_fraud_tenant_secret or tenant_secret or "").strip() or None
    rows, lock = list_saved_stamps(entity, secret)
    if lock == "locked":
        return FraudStampGallery(
            entity_id=entity,
            stamps=[],
            locked=True,
            message="Saved stamps exist but this browser needs the enrollment secret. Save a stamp once from this browser, or clear site data and enroll again.",
        )
    return FraudStampGallery(
        entity_id=entity,
        stamps=[FraudStampSpecimen(**item) for item in rows],
        message="No saved stamps yet." if not rows else "",
    )


@router.post("/fraud/decide", response_model=FraudDecideResult)
async def fraud_decide(body: FraudDecideRequest) -> FraudDecideResult:
    try:
        result = decide_enrollment(body.proposal_id, body.approve, body.tenant_secret)
    except httpx.HTTPError as error:
        return FraudDecideResult(
            proposal_id=body.proposal_id,
            enrolled=False,
            decision="error",
            reason=type(error).__name__,
            message="The fraud service did not respond. Is run.cmd still running?",
        )
    enrolled = bool(result.get("enrolled"))
    decision = str(result.get("decision") or result.get("reason") or "")
    if body.approve and enrolled:
        message = "Saved. Upload the same document again to see a match."
    elif body.approve:
        message = "Could not save this mark. Try uploading again."
    else:
        message = "Skipped — nothing was saved."
    return FraudDecideResult(
        proposal_id=body.proposal_id,
        enrolled=enrolled,
        decision=decision or None,
        reason=str(result.get("reason") or "") or None,
        tenant_secret=result.get("tenant_secret"),
        message=message,
    )
