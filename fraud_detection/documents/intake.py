"""Read an uploaded image or PDF and attach the mark review to a score."""

from __future__ import annotations

import base64

import numpy as np
from PIL import Image

from fraud_detection.documents.specimens import _MAX_BYTES, limit_rgb, decode_image
from fraud_detection.schema import Decision, DocumentReview, FraudAssessment, SignalView

_MAX_PAGES = 5
_WARNING_SIGNAL = {
    "missing_stamp": (
        "document_missing_stamp",
        "medium",
        "The uploaded document has no stamp.",
        45,
    ),
    "missing_signature": (
        "document_missing_signature",
        "medium",
        "The uploaded document has no signature.",
        45,
    ),
    "stamp_mismatch": (
        "document_stamp_mismatch",
        "high",
        "The stamp on the uploaded document does not match the saved stamp.",
        60,
    ),
    "stamp_unrecognized": (
        "document_stamp_unrecognized",
        "high",
        "This stamp is about something else. It is not marked fraudulent. Approve the crop to enroll it as a new genuine stamp, or leave the warning.",
        60,
    ),
    "stamp_fraudulent": (
        "document_stamp_fraudulent",
        "high",
        "This stamp has the same content as a saved stamp, but the drawing is not the genuine one. It is fraudulent.",
        75,
    ),
    "stamp_uncertain": (
        "document_stamp_uncertain",
        "high",
        "The stamp wording is close to a saved stamp, but the scan is not clear enough to call the drawing genuine or fraudulent. Review it manually.",
        60,
    ),
    "signature_mismatch": (
        "document_signature_mismatch",
        "high",
        "The signature on the uploaded document does not match the saved signature.",
        60,
    ),
    "signature_unrecognized": (
        "document_signature_unrecognized",
        "high",
        "This signature does not match a saved signature. It is not marked fraudulent. Approve the crop to enroll it as a new genuine signature, or leave the warning.",
        60,
    ),
    "unreadable_document": (
        "document_unreadable",
        "medium",
        "The uploaded document could not be read.",
        None,
    ),
    "no_file": (
        "document_unreadable",
        "medium",
        "The score included a document field but no file.",
        None,
    ),
}


def _excerpt(parts: list[str]) -> str | None:
    text = " ".join(part.strip() for part in parts if part and part.strip())
    text = " ".join(text.split())
    if not text:
        return None
    return text[:240]


def render_pdf(pdf_base64: str) -> tuple[list[np.ndarray], str | None]:
    raw = base64.b64decode(pdf_base64, validate=False)
    if not raw or len(raw) > _MAX_BYTES:
        raise ValueError("unreadable_document")
    try:
        import pymupdf
    except ImportError as exc:
        raise ValueError("unreadable_document") from exc
    try:
        document = pymupdf.open(stream=raw, filetype="pdf")
    except Exception as exc:
        raise ValueError("unreadable_document") from exc
    pages: list[np.ndarray] = []
    texts: list[str] = []
    try:
        if document.page_count == 0:
            raise ValueError("unreadable_document")
        for index, page in enumerate(document):
            if index >= _MAX_PAGES:
                break
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            pages.append(limit_rgb(image))
            texts.append(page.get_text("text") or "")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("unreadable_document") from exc
    finally:
        document.close()
    if not pages:
        raise ValueError("unreadable_document")
    return pages, _excerpt(texts)


def pdf_clues(pdf_base64: str | None) -> dict:
    """Structural clues from a PDF. Absence of a PDF means these clues do not exist.

    An image object is not proof of a pasted stamp. The genuine labellisation
    file already has one, and a phone scan of a paper page is often one image.
    An exact copy of the stamp crop cannot be separated from a recapture of
    that same digital stamp.
    """
    if not pdf_base64:
        return {
            "available": False,
            "reason": "not_a_pdf",
            "exact_stamp_copy_from_crop_alone": False,
        }
    raw = base64.b64decode(pdf_base64, validate=False)
    if not raw or len(raw) > _MAX_BYTES:
        return {"available": False, "reason": "unreadable_pdf", "exact_stamp_copy_from_crop_alone": False}
    try:
        import pymupdf
    except ImportError:
        return {"available": False, "reason": "pymupdf_missing", "exact_stamp_copy_from_crop_alone": False}
    try:
        document = pymupdf.open(stream=raw, filetype="pdf")
    except Exception:
        return {"available": False, "reason": "unreadable_pdf", "exact_stamp_copy_from_crop_alone": False}
    images = 0
    drawings = 0
    try:
        if document.page_count == 0:
            return {"available": False, "reason": "no_pages", "exact_stamp_copy_from_crop_alone": False}
        for index, page in enumerate(document):
            if index >= _MAX_PAGES:
                break
            images += len(page.get_images(full=True) or [])
            drawings += len(page.get_drawings() or [])
    except Exception:
        return {"available": False, "reason": "unreadable_pdf", "exact_stamp_copy_from_crop_alone": False}
    finally:
        document.close()
    return {
        "available": True,
        "image_objects": images,
        "drawings": drawings,
        "exact_stamp_copy_from_crop_alone": False,
    }


def load_pages(image_base64: str | None, pdf_base64: str | None) -> tuple[str, list[np.ndarray], str | None]:
    if pdf_base64:
        pages, excerpt = render_pdf(pdf_base64)
        return "pdf", pages, excerpt
    if image_base64:
        return "image", [decode_image(image_base64)], None
    raise ValueError("no_file")


def unread_review(source: str, reason: str) -> dict:
    return {
        "checked": False,
        "source": source,
        "pages": 0,
        "warnings": [reason],
        "approval_required": False,
        "marks": [],
        "proof": False,
        "text_excerpt": None,
        "note": "The file could not be read. The payment was still scored.",
    }


def _decision_for(score: int) -> Decision:
    if score >= 75:
        return Decision.HIGH_RISK
    if score >= 45:
        return Decision.MEDIUM_RISK
    return Decision.LOW_RISK


def merge_document_review(assessment: FraudAssessment, review: dict) -> FraudAssessment:
    signals = list(assessment.signals)
    evidence = list(assessment.evidence)
    fraud_types = list(assessment.fraud_types)
    risk = assessment.risk_score
    review_flag = assessment.requires_human_review
    sentences: list[str] = []
    for warning in review.get("warnings") or []:
        spec = _WARNING_SIGNAL.get(str(warning))
        if spec is None:
            continue
        name, severity, detail, floor = spec
        if name not in fraud_types:
            fraud_types.append(name)
        signals.append(SignalView(signal=name, severity=severity, detail=detail))
        evidence.append(detail)
        sentences.append(detail)
        review_flag = True
        if floor is not None:
            risk = max(risk, floor)
    if review.get("approval_required"):
        sentences.append(
            "A stamp or signature was cropped from the file and is waiting for approval before it is saved."
        )
    decision = assessment.decision
    risk_level = assessment.risk_level
    if risk != assessment.risk_score:
        decision = _decision_for(risk)
        risk_level = decision.value
    explanation = assessment.explanation
    if sentences:
        explanation = f"{explanation} {' '.join(sentences)}".strip()
    return assessment.model_copy(
        update={
            "signals": signals,
            "evidence": evidence,
            "fraud_types": fraud_types,
            "risk_score": risk,
            "decision": decision,
            "risk_level": risk_level,
            "requires_human_review": review_flag,
            "explanation": explanation,
            "documents": DocumentReview.model_validate(review),
        }
    )
