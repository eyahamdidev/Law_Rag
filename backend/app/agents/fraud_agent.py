"""Connector to the fraud detection service (fraud_detection/, port 8100).

The service is the teammate's own HTTP microservice: rules, LightGBM, anomaly
and graph scores, sanctions screening and a stamp/signature check on uploaded
invoices. Following its handoff spec, this agent only calls it over HTTP and
never imports its models or re-estimates its scores.

    1. Extract  prompt fraud.extract_transaction turns the founder's message and
                the invoice text into amount, currency, date, counterparty...
    2. Score    POST /v1/score with that transaction, the founder's earlier
                payments in this session as history (so a repeated invoice is
                caught), and the uploaded file for the stamp check.
    3. Describe the reply is written by code from the service's JSON, not by an
                LLM, so the risk level, score and signals cannot be distorted.

A contract-fairness question, or a request with neither an amount nor a file,
is answered without calling the service.
"""

import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime

import httpx

from app.agents.base import Agent
from app.config import settings
from app.prompts.library import get_prompt
from app.schemas.agents import AgentCard, AgentRequest, AgentResult
from app.schemas.common import ModuleStatus, TraceStep
from app.services.llm import LLMUnavailable, get_llm

LEDGER_SIZE = 50
# Payment method -> (transaction_type, channel) as the service's specialist routing reads them
# (fraud_detection/models/supervised.py): mobile money is recognised by its channel, not its type.
METHODS = {
    "transfer": ("transfer", None),
    "card": ("card", "card"),
    "cash": ("cash", None),
    "cheque": ("cheque", None),
    "mobile_money": ("transfer", "mobile"),
}

TEXT = {
    "fr": {
        "level": {"HIGH_RISK": "élevé", "MEDIUM_RISK": "moyen", "LOW_RISK": "faible"},
        "head": "Niveau de risque : {level} ({score}/100).",
        "review": "Une vérification par une personne est recommandée avant de payer.",
        "signals": "Signaux relevés par le service (détail en anglais) :",
        "none": "Aucun signal de fraude n'a été relevé pour ce paiement.",
        "stamp": "Cachet / signature :",
        "coverage": "Données partielles : le score est moins fiable (couverture {cov}).",
        "note": "Ce score résume des indices ; ce n'est ni une probabilité ni une preuve de fraude.",
        "ask": "Pour vérifier un paiement ou une facture, indiquez le montant, le fournisseur et la date, ou joignez la facture (PDF ou photo).",
        "contract": "La vérification de l'équité d'un contrat (clauses abusives) n'est pas encore disponible. Le service vérifie les paiements, les factures et les cachets.",
        "down": "Le service de détection de fraude ne répond pas. Il se lance avec : python -m fraud_detection serve --port 8100",
    },
    "en": {
        "level": {"HIGH_RISK": "high", "MEDIUM_RISK": "medium", "LOW_RISK": "low"},
        "head": "Risk level: {level} ({score}/100).",
        "review": "A person should review this before paying.",
        "signals": "Signals raised by the service:",
        "none": "No fraud signal was raised for this payment.",
        "stamp": "Stamp / signature:",
        "coverage": "Some details are missing, so the score is less reliable (coverage {cov}).",
        "note": "This score summarises evidence; it is not a probability or proof of fraud.",
        "ask": "To check a payment or an invoice, give the amount, the supplier and the date, or attach the invoice (PDF or photo).",
        "contract": "Checking whether a contract is fair (unfair clauses) is not available yet. The service checks payments, invoices and stamps.",
        "down": "The fraud detection service is not responding. Start it with: python -m fraud_detection serve --port 8100",
    },
    "ar": {
        "level": {"HIGH_RISK": "مرتفع", "MEDIUM_RISK": "متوسط", "LOW_RISK": "منخفض"},
        "head": "مستوى الخطر: {level} ({score}/100).",
        "review": "يُنصح بمراجعة بشرية قبل الدفع.",
        "signals": "المؤشرات التي رصدها النظام (التفاصيل بالإنجليزية):",
        "none": "لم يُرصد أي مؤشر احتيال لهذه العملية.",
        "stamp": "الختم / الإمضاء:",
        "coverage": "بعض المعطيات ناقصة، لذلك النتيجة أقل موثوقية (التغطية {cov}).",
        "note": "هذه النتيجة تلخص مؤشرات، وليست احتمالا ولا دليلا على الاحتيال.",
        "ask": "للتثبت من دفعة أو فاتورة، اذكر المبلغ والمزوّد والتاريخ، أو أرفق الفاتورة (PDF أو صورة).",
        "contract": "التثبت من عدالة العقود (الشروط التعسفية) غير متوفر بعد. يتحقق النظام من الدفعات والفواتير والأختام.",
        "down": "خدمة كشف الاحتيال لا تستجيب. تُشغَّل بالأمر: python -m fraud_detection serve --port 8100",
    },
}


def _slug(text: str | None, default: str) -> str:
    # Fold accents first ("Médina" -> "medina"), so the service's explanation shows readable ids.
    folded = "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return value[:48] or default


def _ledger_path(session_id: str):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80]
    return settings.data_dir / "fraud_ledger" / f"{safe}.json"


def load_ledger(session_id: str | None) -> list[dict]:
    if not session_id:
        return []
    path = _ledger_path(session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        return []


def save_ledger(session_id: str | None, history: list[dict], transaction: dict) -> None:
    if not session_id:
        return
    path = _ledger_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps((history + [transaction])[-LEDGER_SIZE:], ensure_ascii=False), encoding="utf-8")


def build_transaction(fields: dict, request: AgentRequest) -> dict:
    """Map extracted fields onto the service's Transaction schema."""
    payer = request.profile.known().get("company_name") or request.profile.known().get("founder_name")
    sender_id = _slug(payer, "founder-" + (request.session_id or "anonymous")[:12])
    receiver_id = _slug(fields.get("counterparty_name"), "unknown-counterparty")
    date = fields.get("date") or ""
    timestamp = f"{date}T12:00:00" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else datetime.now().replace(microsecond=0).isoformat()
    fingerprint = json.dumps([fields.get("amount"), receiver_id, fields.get("invoice_number"), timestamp, time.time()])
    tx_type, channel = METHODS.get(fields.get("payment_method") or "", ("transfer", None))
    return {
        "transaction_id": "tx-" + hashlib.sha1(fingerprint.encode()).hexdigest()[:12],
        "timestamp": timestamp,
        "amount": float(fields.get("amount") or 0),
        "currency": (fields.get("currency") or "TND").upper(),
        "transaction_type": tx_type,
        "channel": channel,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "sender_name": payer,
        "receiver_name": fields.get("counterparty_name"),
        "country_from": "TN",
        "country_to": (fields.get("counterparty_country") or "TN").upper(),
        "invoice_id": fields.get("invoice_number"),
        "description": fields.get("description"),
    }


def document_payload(request: AgentRequest, entity_id: str) -> dict | None:
    for attachment in request.attachments:
        if not attachment.data_base64:
            continue
        is_pdf = attachment.mime == "application/pdf" or attachment.filename.lower().endswith(".pdf")
        return {
            "entity_id": entity_id,
            "filename": attachment.filename,
            ("pdf_base64" if is_pdf else "image_base64"): attachment.data_base64,
        }
    return None


def describe(result: dict, language: str) -> str:
    """The founder-facing text, written only from the service's own fields."""
    t = TEXT.get(language, TEXT["fr"])
    level = result.get("risk_level", "LOW_RISK")
    lines = [t["head"].format(level=t["level"].get(level, level), score=result.get("risk_score", "?"))]
    if result.get("requires_human_review"):
        lines.append(t["review"])
    signals = result.get("signals") or []
    if signals:
        lines.append(t["signals"])
        lines += [f"- {s.get('detail') or s.get('signal')} ({s.get('severity')})" for s in signals[:6]]
    else:
        lines.append(t["none"])
    review = result.get("documents") or {}
    marks = review.get("marks") or []
    if marks or review.get("warnings"):
        lines.append(t["stamp"])
        for mark in marks[:4]:
            detail = mark.get("question") or mark.get("review_reason") or ""
            lines.append(f"- {mark.get('kind')}: {mark.get('status')}" + (f" ({detail})" if detail else ""))
        lines += [f"- {w}" for w in (review.get("warnings") or [])[:3]]
    if result.get("data_coverage") in {"LOW", "MEDIUM"}:
        lines.append(t["coverage"].format(cov=result["data_coverage"]))
    lines.append(t["note"])
    return "\n".join(lines)


class FraudAgent(Agent):
    def __init__(self, card: AgentCard) -> None:
        self.card = card

    def _extract(self, request: AgentRequest) -> tuple[dict, str]:
        prompt = get_prompt("fraud.extract_transaction")
        document_text = "\n\n".join(a.text[:3000] for a in request.attachments if a.text)[:4000]
        data, result = get_llm().chat_json(
            prompt.messages(question=request.question, document_text=document_text or "(none)"),
            tier="fast",
            max_tokens=400,
        )
        return data, f"{prompt.ref} via {result.provider}/{result.model}"

    def run(self, request: AgentRequest) -> AgentResult:
        t = TEXT.get(request.language, TEXT["fr"])
        trace: list[TraceStep] = []
        try:
            fields, ref = self._extract(request)
        except (LLMUnavailable, ValueError) as error:
            return AgentResult(agent=self.id, status="error", answer=t["ask"],
                               trace=[TraceStep(module="agent.fraud.extract", status=ModuleStatus.skipped, detail=str(error)[:200])])
        trace.append(TraceStep(module="agent.fraud.extract", status=ModuleStatus.ok,
                               detail=f"kind={fields.get('kind')}, amount={fields.get('amount')} {fields.get('currency')}, counterparty={fields.get('counterparty_name')} ({ref})"))

        has_file = any(a.data_base64 for a in request.attachments)
        if fields.get("kind") == "contract" and not has_file:
            return AgentResult(agent=self.id, status="abstained", answer=t["contract"], trace=trace)
        if not isinstance(fields.get("amount"), (int, float)) and not has_file:
            return AgentResult(agent=self.id, status="needs_info", answer=t["ask"], missing_info=[t["ask"]], trace=trace)

        transaction = build_transaction(fields, request)
        history = load_ledger(request.session_id)
        payload = {"transaction": transaction, "history": history}
        document = document_payload(request, transaction["receiver_id"])
        if document:
            payload["document"] = document
        started = time.perf_counter()
        try:
            response = httpx.post(f"{settings.fraud_service_url}/v1/score", json=payload, timeout=settings.fraud_timeout_s)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPError as error:
            trace.append(TraceStep(module="agent.fraud.score", status=ModuleStatus.skipped,
                                   detail=f"{settings.fraud_service_url}: {type(error).__name__}: {str(error)[:150]}"))
            return AgentResult(agent=self.id, status="error", answer=t["down"], trace=trace)
        save_ledger(request.session_id, history, transaction)
        trace.append(TraceStep(module="agent.fraud.score", status=ModuleStatus.ok, detail=(
            f"{result.get('risk_level')} {result.get('risk_score')}/100, labels={result.get('label_types')}, "
            f"coverage={result.get('data_coverage')}, history={len(history)}, document={'yes' if document else 'no'} "
            f"[{(time.perf_counter() - started) * 1000:.0f} ms]")))
        return AgentResult(
            agent=self.id,
            status="ok",
            answer=describe(result, request.language),
            confidence=result.get("model_confidence"),
            trace=trace,
        )
