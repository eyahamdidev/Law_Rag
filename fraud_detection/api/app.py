from __future__ import annotations

import os
from pathlib import Path

import joblib
from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator

from fraud_detection.entity_intelligence.loaders import load_rne_csv, load_sanctions_csv
from fraud_detection.entity_intelligence.registry import EntityRegistry
from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.models.general_behavior import GeneralBehavior
from fraud_detection.models.population_anomaly import PopulationAnomaly
from fraud_detection.models.supervised import SupervisedDetector
from fraud_detection.models.ulb_specialist import ULBCardSpecialist
from fraud_detection.documents.intake import load_pages, merge_document_review, pdf_clues, unread_review
from fraud_detection.documents.specimens import SpecimenStore, decode_image, tenant_key
from fraud_detection.normalize import normalize_transaction_payload
from fraud_detection.paths import ARTIFACTS, STAMP_VERIFIER
from fraud_detection.schema import EntityRecord, FraudAssessment, Transaction


class DocumentRequest(BaseModel):
    entity_id: str
    image_base64: str
    kind: str | None = None
    expect_stamp: bool = True
    expect_signature: bool = True
    comment: str | None = None
    tenant_secret: str | None = None


class DocumentAttachment(BaseModel):
    entity_id: str | None = None
    image_base64: str | None = None
    pdf_base64: str | None = None
    filename: str | None = None
    expect_stamp: bool = True
    expect_signature: bool = True
    comment: str | None = None
    tenant_secret: str | None = None


class DecideRequest(BaseModel):
    proposal_id: str
    approve: bool
    comment: str | None = None
    tenant_secret: str | None = None


class ScoreRequest(BaseModel):
    transaction: Transaction
    history: list[Transaction] = Field(default_factory=list)
    entities: list[EntityRecord] = Field(default_factory=list)
    document: DocumentAttachment | None = None

    @field_validator("transaction", mode="before")
    @classmethod
    def _normalize_transaction(cls, value):
        if isinstance(value, dict):
            return normalize_transaction_payload(value)
        return value

    @field_validator("history", mode="before")
    @classmethod
    def _normalize_history(cls, value):
        if not isinstance(value, list):
            return value
        return [normalize_transaction_payload(item) if isinstance(item, dict) else item for item in value]


def engine_from_env() -> FraudDetectionEngine:
    model_env = os.environ.get("FRAUD_MODEL_PATH")
    model_path = Path(model_env) if model_env else ARTIFACTS / "supervised.joblib"
    supervised = SupervisedDetector.load(model_path) if model_path.exists() else None
    anomaly_env = os.environ.get("FRAUD_ANOMALY_PATH")
    anomaly_path = Path(anomaly_env) if anomaly_env else ARTIFACTS / "anomaly.joblib"
    population = PopulationAnomaly.load(anomaly_path) if anomaly_path.exists() else None
    sanctions = SanctionsIndex([])
    sanctions_env = os.environ.get("FRAUD_SANCTIONS_CSV")
    sanctions_cache = ARTIFACTS / "sanctions.joblib"
    if sanctions_env and Path(sanctions_env).exists():
        sanctions = SanctionsIndex(load_sanctions_csv(sanctions_env))
    elif sanctions_cache.exists():
        loaded = joblib.load(sanctions_cache)
        if isinstance(loaded, SanctionsIndex):
            sanctions = loaded
    registry = EntityRegistry([])
    rne_path = os.environ.get("FRAUD_RNE_CSV")
    if rne_path and Path(rne_path).exists():
        registry = EntityRegistry(load_rne_csv(rne_path))
    general_path = ARTIFACTS / "general_behavior.joblib"
    ulb_path = ARTIFACTS / "ulb_card.joblib"
    general = GeneralBehavior.load(general_path) if general_path.exists() else None
    ulb = ULBCardSpecialist.load(ulb_path) if ulb_path.exists() else None
    return FraudDetectionEngine(
        supervised=supervised,
        sanctions=sanctions,
        registry=registry,
        population_anomaly=population,
        general_behavior=general,
        ulb_specialist=ulb,
    )


def create_app(engine: FraudDetectionEngine | None = None) -> FastAPI:
    app = FastAPI(
        title="Fraud detection agent",
        version="0.1.0",
        summary="Rules, supervised ML, anomaly detection, graph patterns, and entity intelligence.",
    )
    app.state.engine = engine or engine_from_env()

    @app.get("/health")
    def health() -> dict:
        current: FraudDetectionEngine = app.state.engine
        return {
            "status": "ok",
            "layers": ["rules", "supervised", "anomaly", "graph", "entity_intelligence"],
            "supervised_loaded": current.supervised is not None,
            "anomaly_loaded": current.population_anomaly is not None,
            "sanctions_available": current.sanctions.available,
            "supervised_backend": None if current.supervised is None else current.supervised.backend,
            "general_behavior_loaded": current.general_behavior is not None,
            "ulb_loaded": current.ulb_specialist is not None,
            "tunisia_model_trained": False,
            "tunisia_score_policy": "null_until_real_labeled_transactions",
            "document_check": True,
            "document_review_on_score": True,
            "stamp_verifier_loaded": STAMP_VERIFIER.is_file(),
            "stamp_verifier_method": "supervised",
            "stamp_verdict_uses_model": False,
            "enrolled_specimens": _specimens().enrolled_count(),
        }

    def _specimens() -> SpecimenStore:
        store = getattr(app.state, "specimens", None) or SpecimenStore()
        app.state.specimens = store
        return store

    def _score_one(request: ScoreRequest) -> FraudAssessment:
        current: FraudDetectionEngine = app.state.engine
        assessment = current.score(request.transaction, request.history, request.entities)
        attachment = request.document
        if attachment is None:
            return assessment
        source = "pdf" if attachment.pdf_base64 else "image"
        try:
            loaded_source, pages, excerpt = load_pages(attachment.image_base64, attachment.pdf_base64)
            tenant = tenant_key(attachment.entity_id, request.transaction.receiver_id)
            if tenant is None:
                review = {
                    "checked": False,
                    "source": loaded_source,
                    "pages": len(pages),
                    "warnings": ["missing_tenant"],
                    "approval_required": False,
                    "marks": [],
                    "proof": False,
                    "text_excerpt": None,
                    "note": "No organization id was provided. The file was not compared and nothing was saved.",
                    "forensics": {},
                }
            elif _specimens().tenant_is_locked(tenant) and not _specimens().tenant_authorized(tenant, attachment.tenant_secret):
                review = {
                    "checked": False,
                    "source": loaded_source,
                    "pages": len(pages),
                    "warnings": ["tenant_unauthorized"],
                    "approval_required": False,
                    "marks": [],
                    "proof": False,
                    "text_excerpt": None,
                    "forensics": {},
                    "note": "This organization already has a saved reference. The request did not present its tenant secret, so the stamp was not compared and nothing was changed.",
                }
            else:
                review = _specimens().review_pages(
                    tenant,
                    pages,
                    expect_stamp=attachment.expect_stamp,
                    expect_signature=attachment.expect_signature,
                    source=loaded_source,
                    text_excerpt=excerpt,
                    comment=attachment.comment,
                    forensics=pdf_clues(attachment.pdf_base64),
                )
        except (ValueError, OSError):
            reason = "no_file" if not attachment.image_base64 and not attachment.pdf_base64 else "unreadable_document"
            review = unread_review(source, reason)
        return merge_document_review(assessment, review)

    @app.post("/v1/score", response_model=FraudAssessment)
    def score(request: ScoreRequest) -> FraudAssessment:
        return _score_one(request)

    @app.post("/v1/documents/enroll")
    def enroll_document(request: DocumentRequest) -> dict:
        if request.kind not in {"stamp", "signature"}:
            return {"enrolled": False, "reason": "kind must be stamp or signature", "specimen_id": None}
        if tenant_key(request.entity_id) is None:
            return {"enrolled": False, "reason": "missing_tenant", "specimen_id": None, "entity_id": None}
        if _specimens().tenant_is_locked(request.entity_id) and not _specimens().tenant_authorized(request.entity_id, request.tenant_secret):
            return {"enrolled": False, "reason": "tenant_unauthorized", "specimen_id": None, "entity_id": request.entity_id}
        try:
            gray = decode_image(request.image_base64)
        except (ValueError, OSError):
            return {"enrolled": False, "reason": "unreadable_image", "specimen_id": None}
        return _specimens().enroll(request.entity_id, request.kind, gray, comment=request.comment)

    @app.post("/v1/documents/decide")
    def decide_document(request: DecideRequest) -> dict:
        return _specimens().decide(
            request.proposal_id,
            request.approve,
            comment=request.comment,
            tenant_secret=request.tenant_secret,
        )

    @app.post("/v1/documents/check")
    def check_document(request: DocumentRequest) -> dict:
        if tenant_key(request.entity_id) is None:
            return {
                "entity_id": None,
                "stamp_present": False,
                "signature_present": False,
                "warnings": ["missing_tenant"],
                "matches": {},
                "proof": False,
                "note": "No organization id was provided. Nothing was compared and nothing was saved.",
            }
        if _specimens().tenant_is_locked(request.entity_id) and not _specimens().tenant_authorized(request.entity_id, request.tenant_secret):
            return {
                "entity_id": request.entity_id,
                "stamp_present": False,
                "signature_present": False,
                "warnings": ["tenant_unauthorized"],
                "matches": {},
                "proof": False,
                "note": "This organization already has a saved reference. The request did not present its tenant secret.",
            }
        try:
            gray = decode_image(request.image_base64)
        except (ValueError, OSError):
            return {
                "entity_id": request.entity_id,
                "stamp_present": False,
                "signature_present": False,
                "warnings": ["unreadable_image"],
                "matches": {},
                "proof": False,
                "note": "The image could not be read.",
            }
        return _specimens().check(
            request.entity_id,
            gray,
            expect_stamp=request.expect_stamp,
            expect_signature=request.expect_signature,
        )

    @app.post("/v1/score/batch", response_model=list[FraudAssessment])
    def score_batch(requests: list[ScoreRequest]) -> list[FraudAssessment]:
        return [_score_one(item) for item in requests]

    return app


app = create_app()
