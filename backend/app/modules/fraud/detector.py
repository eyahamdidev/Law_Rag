"""Score uploads through the fraud_detection service (POST /v1/score).

Two modes:
- stamp: PDF or image + organization id → stamp/signature review on the document.
- payment: JSON score payload, or PDF/text from which we extract a transaction JSON
  (same shape as the fraud agent) then score.

Uploads are not written to disk.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any

import httpx

from app.agents.fraud_agent import build_transaction
from app.config import settings
from app.modules.intake.extractor import inspect_document
from app.prompts.library import get_prompt
from app.schemas.agents import AgentRequest, FounderProfile
from app.schemas.common import ModuleStatus, TraceStep
from app.schemas.fraud import FraudEnrollmentPrompt, FraudReport, FraudSignal
from app.services.llm import LLMUnavailable, get_llm

_PLACEHOLDER_SUMMARY = (
    "The file was received and hashed. The fraud detection service is not "
    "responding, so there is no score yet. Start it with "
    "`python -m fraud_detection serve --port 8100` (or use run.cmd)."
)

_RISK_LABEL = {
    "LOW_RISK": "low",
    "MEDIUM_RISK": "medium",
    "HIGH_RISK": "high",
}


def _document_attachment(
    filename: str,
    content: bytes,
    entity_id: str,
    tenant_secret: str | None = None,
    *,
    check_stamp: bool = True,
) -> dict[str, Any]:
    encoded = base64.b64encode(content).decode("ascii")
    name = (filename or "upload").lower()
    doc: dict[str, Any] = {
        "entity_id": entity_id,
        "filename": filename,
        "expect_stamp": check_stamp,
        "expect_signature": False,
    }
    if tenant_secret:
        doc["tenant_secret"] = tenant_secret
    if name.endswith(".pdf"):
        doc["pdf_base64"] = encoded
    else:
        doc["image_base64"] = encoded
    return doc


def _minimal_transaction(transaction_id: str, receiver_id: str, description: str) -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "timestamp": datetime.now().replace(microsecond=0).isoformat(),
        "amount": 0.0,
        "currency": "TND",
        "transaction_type": "transfer",
        "sender_id": "fraud-tab",
        "receiver_id": receiver_id,
        "country_from": "TN",
        "country_to": "TN",
        "description": description,
    }


def _build_stamp_payload(
    filename: str,
    content: bytes,
    entity_id: str | None,
    digest: str,
    tenant_secret: str | None = None,
) -> dict[str, Any]:
    org = (entity_id or "").strip() or f"upload-{digest[:12]}"
    tx_id = f"stamp-{digest[:12]}"
    return {
        "transaction": _minimal_transaction(tx_id, org, "Stamp verification"),
        "history": [],
        "document": _document_attachment(filename, content, org, tenant_secret, check_stamp=True),
    }


def _parse_score_json(content: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError('Payment JSON must be an object with a "transaction" field.')
    if "transaction" not in payload:
        raise ValueError(
            'Payment JSON must match POST /v1/score: include a "transaction" object, '
            'and optionally "history", "entities", and "document".'
        )
    return payload


def _extract_payment_fields(document_text: str) -> tuple[dict[str, Any], TraceStep]:
    prompt = get_prompt("fraud.extract_transaction")
    try:
        data, result = get_llm().chat_json(
            prompt.messages(
                question="Extract payment details from this uploaded document for fraud screening.",
                document_text=document_text or "(empty)",
            ),
            tier="fast",
            max_tokens=400,
        )
    except LLMUnavailable as error:
        raise ValueError(
            "Could not read the document into a payment JSON: the language model is unavailable. "
            "Upload a .json score payload instead."
        ) from error
    except ValueError as error:
        raise ValueError(f"Could not extract payment fields: {error}") from error
    detail = (
        f"kind={data.get('kind')}, amount={data.get('amount')} {data.get('currency')}, "
        f"counterparty={data.get('counterparty_name')} ({result.provider}/{result.model})"
    )
    return data, TraceStep(module="fraud.extract", status=ModuleStatus.ok, detail=detail)


def _attach_document_if_binary(
    payload: dict[str, Any],
    filename: str,
    content: bytes,
    *,
    check_stamp: bool = False,
) -> None:
    name = (filename or "").lower()
    if name.endswith(".json"):
        return
    if payload.get("document"):
        return
    receiver = payload.get("transaction", {}).get("receiver_id") or "unknown-receiver"
    payload["document"] = _document_attachment(filename, content, str(receiver), check_stamp=check_stamp)


def _build_payment_payload(
    filename: str,
    content: bytes,
    digest: str,
) -> tuple[dict[str, Any], list[TraceStep]]:
    steps: list[TraceStep] = []
    name = (filename or "upload").lower()

    if name.endswith(".json"):
        payload = _parse_score_json(content)
        steps.append(
            TraceStep(
                module="fraud.payload",
                status=ModuleStatus.ok,
                detail='Loaded POST /v1/score JSON (keys: "transaction", optional "history", "entities", "document").',
            )
        )
        return payload, steps

    attachment, intake = inspect_document(filename, content, "")
    steps.append(intake)
    fields, extract_step = _extract_payment_fields(attachment.text)
    steps.append(extract_step)

    if not isinstance(fields.get("amount"), (int, float)):
        raise ValueError(
            "No payment amount was found in this file. For payment scoring, upload a .json file "
            'in POST /v1/score shape, or a PDF/invoice that states amount and counterparty.'
        )

    request = AgentRequest(
        task="Score this payment",
        question="Fraud tab payment upload",
        profile=FounderProfile(),
        attachments=[attachment],
    )
    transaction = build_transaction(fields, request)
    payload: dict[str, Any] = {"transaction": transaction, "history": []}
    _attach_document_if_binary(payload, filename, content, check_stamp=False)
    steps.append(
        TraceStep(
            module="fraud.payload",
            status=ModuleStatus.ok,
            detail=f"Built transaction {transaction.get('transaction_id')} for POST /v1/score.",
        )
    )
    return payload, steps


def _enrollment_prompts(result: dict) -> list[FraudEnrollmentPrompt]:
    prompts: list[FraudEnrollmentPrompt] = []
    for mark in (result.get("documents") or {}).get("marks") or []:
        proposal_id = mark.get("proposal_id")
        if not proposal_id:
            continue
        kind = str(mark.get("kind") or "mark")
        if kind != "stamp":
            continue
        status = str(mark.get("status") or "")
        verdict = str(mark.get("verdict") or "")
        if status != "awaiting_approval" and verdict != "unrecognized":
            continue
        if verdict == "unrecognized":
            title = "New stamp — add it?"
        else:
            title = "Save this stamp?"
        prompts.append(
            FraudEnrollmentPrompt(
                kind=kind,
                proposal_id=str(proposal_id),
                preview_base64=mark.get("crop_base64"),
                title=title,
            )
        )
    return prompts


def _summary_from_score(result: dict, *, mode: str, enrollments: list[FraudEnrollmentPrompt]) -> str:
    review = result.get("documents") or {}
    marks = review.get("marks") or []
    score = result.get("risk_score")
    level = _RISK_LABEL.get(str(result.get("risk_level") or ""), "checked")

    if enrollments:
        return "We found a stamp on your file. Use the popup to save it — then the next upload can be compared."

    if mode == "stamp":
        for mark in marks:
            verdict = mark.get("verdict")
            if verdict == "fraudulent":
                return "This stamp does not match your saved reference. Review before you rely on the document."
            if verdict == "genuine":
                return "Stamp matches your saved reference."
            if verdict == "uncertain":
                return "Stamp is unclear on this scan — try a sharper PDF or photo."
        if review.get("warnings"):
            return "Document checked. See details below if something looked missing."
        return "No stamp issues flagged. Risk level: " + level + (f" ({score}/100)." if score is not None else ".")

    if marks:
        return f"Payment scored. Risk: {level}" + (f" ({score}/100)." if score is not None else ".")
    explanation = (result.get("explanation") or "").strip()
    if explanation and len(explanation) < 160:
        return explanation
    return f"Payment scored. Risk: {level}" + (f" ({score}/100)." if score is not None else ".")


def decide_enrollment(
    proposal_id: str,
    approve: bool,
    tenant_secret: str | None = None,
) -> dict[str, Any]:
    url = f"{settings.fraud_service_url.rstrip('/')}/v1/documents/decide"
    payload: dict[str, Any] = {"proposal_id": proposal_id, "approve": approve}
    if tenant_secret:
        payload["tenant_secret"] = tenant_secret
    response = httpx.post(url, json=payload, timeout=settings.fraud_timeout_s)
    response.raise_for_status()
    return response.json()


def _stamp_verdict(result: dict) -> str | None:
    for mark in (result.get("documents") or {}).get("marks") or []:
        if mark.get("kind") != "stamp":
            continue
        verdict = mark.get("verdict") or mark.get("status")
        if verdict:
            return str(verdict)
    return None


def _call_score(payload: dict[str, Any]) -> tuple[dict | None, TraceStep]:
    url = f"{settings.fraud_service_url.rstrip('/')}/v1/score"
    try:
        response = httpx.post(url, json=payload, timeout=settings.fraud_timeout_s)
        response.raise_for_status()
        result = response.json()
        detail = (
            f"{result.get('risk_level')} {result.get('risk_score')}/100, "
            f"labels={result.get('label_types')}, coverage={result.get('data_coverage')}"
        )
        return result, TraceStep(module="fraud.service", status=ModuleStatus.ok, detail=detail)
    except httpx.HTTPError as error:
        return None, TraceStep(
            module="fraud.service",
            status=ModuleStatus.skipped,
            detail=f"{url}: {type(error).__name__}: {str(error)[:150]}",
        )


def analyze_upload(
    filename: str,
    content: bytes,
    mode: str,
    entity_id: str | None = None,
    tenant_secret: str | None = None,
) -> FraudReport:
    kind = mode if mode in {"stamp", "payment"} else "stamp"
    digest = hashlib.sha256(content).hexdigest()
    trace: list[TraceStep] = [
        TraceStep(
            module="fraud.detector",
            status=ModuleStatus.ok,
            detail=f"mode={kind}, SHA-256 {digest[:12]}… (not stored on disk).",
        ),
    ]

    try:
        if kind == "stamp":
            payload = _build_stamp_payload(filename, content, entity_id, digest, tenant_secret)
            _, intake = inspect_document(filename, content, "")
            trace.append(intake)
        else:
            payload, extra = _build_payment_payload(filename, content, digest)
            trace.extend(extra)
    except ValueError as error:
        return FraudReport(
            status=ModuleStatus.skipped,
            filename=filename or "upload",
            document_type=kind,
            document_hash=digest,
            risk_level="unknown",
            signals=[],
            summary=str(error),
            enrollments=[],
            trace=trace,
        )

    scored, score_step = _call_score(payload)
    trace.append(score_step)

    if not scored:
        return FraudReport(
            status=ModuleStatus.placeholder,
            filename=filename or "upload",
            document_type=kind,
            document_hash=digest,
            risk_level="unknown",
            signals=[],
            summary=_PLACEHOLDER_SUMMARY,
            enrollments=[],
            trace=trace,
        )

    enrollments = _enrollment_prompts(scored)
    level = scored.get("risk_level") or scored.get("decision") or "UNKNOWN"
    summary = _summary_from_score(scored, mode=kind, enrollments=enrollments)
    raw_signals = scored.get("signals") or []
    if kind == "payment":
        raw_signals = [item for item in raw_signals if not str(item.get("signal") or "").startswith("document_stamp")]
    signals = [
        FraudSignal(
            code=str(item.get("signal") or "signal"),
            description=str(item.get("detail") or ""),
            severity=str(item.get("severity") or "medium"),
        )
        for item in raw_signals[:12]
    ]
    score_raw = scored.get("risk_score")
    risk_score = int(score_raw) if isinstance(score_raw, (int, float)) else None
    return FraudReport(
        status=ModuleStatus.ok,
        filename=filename or "upload",
        document_type=kind,
        document_hash=digest,
        risk_level=_RISK_LABEL.get(str(level), str(level).lower()),
        risk_score=risk_score,
        stamp_verdict=_stamp_verdict(scored) if kind == "stamp" else None,
        headline=summary,
        signals=signals,
        summary=summary,
        enrollments=enrollments,
        trace=trace,
    )
