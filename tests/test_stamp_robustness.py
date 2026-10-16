"""Live-demo regressions for stamp enrollment and the four verdicts.

Synthetic image edits are labeled as such. They are not a substitute for a
printed counterfeit. The missing-ink cutoff was taken from the four enrolled
PDFs, not from the labeled pages.
"""

import base64
import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageEnhance, ImageFilter

from fraud_detection.api.app import create_app
from fraud_detection.documents.intake import load_pages
from fraud_detection.documents.stamp_alignment import stamp_decision, stamp_verdict
from fraud_detection.documents.specimens import SpecimenStore, crop_array, decode_image, find_marks
from fraud_detection.evaluation.stamp_stress import _perspective
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.paths import GENUINE, PACKAGE, STAMP_DATASET


def test_stamp_verdict_keeps_the_four_outcomes_distinct():
    exact = {"ncc": 1.0, "local_min": 1.0, "quality": "ok", "bright_peak": 0.0, "dark_peak": 0.0}
    assert stamp_verdict("same", exact, 0.2, False) == "genuine"
    # A near-perfect drawing still covers a minor OCR miss.
    assert stamp_verdict("different", exact, 0.1, True) == "genuine"
    assert stamp_verdict("same", {"ncc": 0.90, "local_min": 0.80, "quality": "ok"}, 0.99, True) == "uncertain"
    assert stamp_verdict("different", {"ncc": 0.4, "local_min": 0.1, "quality": "ok"}, 0.9, False) == "unrecognized"
    # Noisy OCR on a drawing that still belongs to this stamp is a review, not a new organization.
    assert stamp_verdict("different", {"ncc": 0.75, "local_min": 0.30, "quality": "ok"}, 0.1, False) == "uncertain"
    # A low score is a failed alignment, not a forgery.
    assert stamp_verdict("same", {"ncc": 0.4, "local_min": 0.0, "quality": "ok"}, 0.05, False) == "uncertain"
    assert stamp_verdict("same", {"ncc": 0.58, "local_min": -0.05, "quality": "ok"}, 0.01, False) == "uncertain"
    # labellisation_0083: similar drawing, mismatched words, model score 0.03.
    assert stamp_verdict(
        "different",
        {"ncc": 0.9016, "local_min": 0.7538, "quality": "ok", "bright_peak": 0.0, "dark_peak": 0.0},
        0.0293,
        False,
    ) == "uncertain"
    # A high model score used to promote an OCR mismatch. Leave-one-document-out
    # PR-AUC on the four identities is about 0.51–0.55, so that score no longer
    # grants genuine. The drawing here is not a close scan, so the verdict abstains.
    mismatch = stamp_decision(
        "different",
        {"ncc": 0.91, "local_min": 0.80, "quality": "ok", "bright_peak": 0.0, "dark_peak": 0.0},
        0.99,
        False,
    )
    assert mismatch["verdict"] == "uncertain"
    assert mismatch["reason_codes"] == ["text_mismatch"]
    assert stamp_verdict("different", {"ncc": 0.85, "local_min": 0.52, "quality": "ok"}, 0.5, True) == "uncertain"
    assert stamp_verdict("same", {"ncc": 0.9, "local_min": 0.6, "quality": "ok"}, 0.5, False) == "uncertain"
    assert stamp_verdict("same", {"ncc": 0.0, "local_min": 0.0, "quality": "failed"}, None, False) == "uncertain"
    assert stamp_verdict("same", {"ncc": 0.57, "local_min": -0.39, "quality": "poor"}, 0.16, False) == "uncertain"
    # JPEG can scramble the words while the pose also fails. That is a review, not a new stamp.
    assert stamp_verdict("different", {"ncc": 0.56, "local_min": -0.32, "quality": "poor"}, 0.2, False) == "uncertain"
    assert stamp_verdict("unknown", {"ncc": 0.3, "local_min": 0.0, "quality": "ok"}, 0.1, False) == "unrecognized"
    hole = {
        "ncc": 0.998,
        "local_min": 0.95,
        "quality": "ok",
        "bright_peak": 160.0,
        "dark_peak": 2.0,
    }
    assert stamp_verdict("same", hole, 0.99, True) == "fraudulent"
    # Same wording and a text-line profile worse than this stamp's own recaptures.
    broken = {
        "ncc": 0.45,
        "local_min": 0.05,
        "quality": "ok",
        "bright_peak": 1.0,
        "dark_peak": 1.0,
        "row_corr": 0.62,
        "row_floor": 0.88,
        "mae": 30.0,
        "low_block": 0.6,
    }
    assert stamp_verdict("same", broken, 0.05, False) == "fraudulent"
    # The same low score with the lines still landing is not fraud.
    assert stamp_verdict("same", {**broken, "row_corr": 0.96}, 0.05, False) == "uncertain"
    # A different organization is unrecognized even when the profile is broken.
    assert stamp_verdict("different", broken, 0.05, False) == "unrecognized"
    close = {
        "ncc": 0.97,
        "local_min": 0.80,
        "quality": "ok",
        "bright_peak": 2.0,
        "dark_peak": 2.0,
        "row_corr": 0.985,
        "row_floor": 0.88,
        "mae": 6.0,
        "low_block": 0.0,
    }
    assert stamp_verdict("same", close, 0.02, False) == "genuine"


def _png_page(crop: Image.Image, *, brightness: float = 1.0, quality: int | None = None) -> str:
    stamp = ImageEnhance.Brightness(crop.convert("RGB")).enhance(brightness)
    scale = 0.55
    resized = stamp.resize(
        (max(1, int(stamp.width * scale)), max(1, int(stamp.height * scale))),
        Image.Resampling.BILINEAR,
    )
    page = Image.new("RGB", (900, 1200), (255, 255, 255))
    page.paste(resized, (900 - resized.width - 70, 1200 - resized.height - 70))
    if quality is not None:
        buffer = io.BytesIO()
        page.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        page = Image.open(buffer).convert("RGB")
    out = io.BytesIO()
    page.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


def _payment(receiver: str = "supplier-9") -> dict:
    return {
        "transaction_id": "pay-stamp",
        "timestamp": "2024-11-18T11:00:00",
        "amount": 125.0,
        "currency": "EUR",
        "transaction_type": "transfer",
        "sender_id": "fr-sender",
        "receiver_id": receiver,
        "country_from": "FR",
        "country_to": "FR",
    }


def _stamp(client: TestClient, image: str, receiver: str = "supplier-9", secret: str | None = None) -> dict:
    document = {"image_base64": image, "expect_signature": False}
    if secret:
        document["tenant_secret"] = secret
    response = client.post(
        "/v1/score",
        json={"transaction": _payment(receiver), "document": document},
    )
    assert response.status_code == 200
    return next(item for item in response.json()["documents"]["marks"] if item["kind"] == "stamp")


def test_declined_enrollment_saves_nothing_and_companies_stay_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    crop = Image.open(next((STAMP_DATASET / "capital" / "stamp_crops").glob("*_reference.jpg"))).convert("RGB")
    image = _png_page(crop)
    first = _stamp(client, image)
    assert first["status"] == "awaiting_approval"
    assert first["proposal_id"]
    declined = client.post("/v1/documents/decide", json={"proposal_id": first["proposal_id"], "approve": False})
    assert declined.json()["enrolled"] is False
    assert not (tmp_path / "index.json").exists()

    again = _stamp(client, image)
    approved = client.post(
        "/v1/documents/decide",
        json={"proposal_id": again["proposal_id"], "approve": True, "comment": "Capital stamp"},
    )
    assert approved.json()["enrolled"] is True
    secret = approved.json()["tenant_secret"]
    assert secret
    repeat = _stamp(client, image, secret=secret)
    assert repeat["verdict"] == "genuine"
    assert repeat["review_recommended"] is False
    assert _stamp(client, image, secret=secret)["verdict"] == "genuine"
    blocked = client.post(
        "/v1/score",
        json={"transaction": _payment(), "document": {"image_base64": image, "expect_signature": False}},
    )
    assert blocked.status_code == 200
    assert blocked.json()["documents"]["checked"] is False
    assert "tenant_unauthorized" in blocked.json()["documents"]["warnings"]
    assert blocked.json()["documents"]["marks"] == []

    other_company = _stamp(client, image, receiver="other-bank")
    assert other_company["status"] == "awaiting_approval"
    assert other_company["verdict"] is None


def test_score_api_accepts_a_darker_copy_and_rejects_a_different_organization(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    capital = next((STAMP_DATASET / "capital" / "stamp_crops").glob("*_reference.jpg"))
    other = next((STAMP_DATASET / "subvention" / "stamp_crops").glob("*_reference.jpg"))
    fake = next((STAMP_DATASET / "capital" / "stamp_crops").glob("*_counterfeit.jpg"))
    enrolled = _png_page(Image.open(capital))
    first = _stamp(client, enrolled)
    approved = client.post("/v1/documents/decide", json={"proposal_id": first["proposal_id"], "approve": True, "comment": "Enrolled"})
    secret = approved.json()["tenant_secret"]

    darker = _stamp(client, _png_page(Image.open(capital), brightness=0.75), secret=secret)
    # A pasted crop can lose a few OCR tokens when it is darkened. That is
    # genuine when the drawing still lines up, and uncertain when it does not.
    # It must not be called fraudulent and must not be offered for enrollment.
    assert darker["verdict"] in {"genuine", "uncertain"}
    assert darker["proposal_id"] is None

    compressed = _stamp(client, _png_page(Image.open(capital), quality=55), secret=secret)
    assert compressed["verdict"] in {"genuine", "uncertain"}
    assert compressed["proposal_id"] is None

    forged = _stamp(client, _png_page(Image.open(fake)), secret=secret)
    assert forged["verdict"] in {"fraudulent", "uncertain"}
    assert forged["verdict"] != "genuine"
    assert forged["proposal_id"] is None

    foreign = _stamp(client, _png_page(Image.open(other)), secret=secret)
    assert foreign["verdict"] == "unrecognized"
    assert foreign["proposal_id"]
    assert foreign["question"]


def test_slight_rotation_is_not_called_fraudulent(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    capital = Image.open(next((STAMP_DATASET / "capital" / "stamp_crops").glob("*_reference.jpg"))).convert("RGB")
    enrolled = _png_page(capital)
    first = _stamp(client, enrolled)
    approved = client.post("/v1/documents/decide", json={"proposal_id": first["proposal_id"], "approve": True, "comment": "Enrolled"})
    turned = capital.rotate(4, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    checked = _stamp(client, _png_page(turned), secret=approved.json()["tenant_secret"])
    assert checked["verdict"] in {"genuine", "uncertain"}
    assert checked["proposal_id"] is None


def test_malformed_image_is_not_genuine(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    response = client.post(
        "/v1/score",
        json={
            "transaction": _payment(),
            "document": {"image_base64": base64.b64encode(b"not-an-image").decode("ascii"), "expect_signature": False},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["documents"]["checked"] is False
    assert "document_unreadable" in body["fraud_types"]
    marks = body["documents"]["marks"]
    assert all(item.get("verdict") != "genuine" for item in marks)


def test_missing_stamp_is_not_genuine(tmp_path):
    store = SpecimenStore(tmp_path)
    blank = decode_image(base64.b64encode(_blank_png()).decode("ascii"))
    result = store.check("supplier-1", blank, expect_signature=False)
    assert result["stamp_present"] is False
    assert result["matches"]["stamp"]["status"] == "missing"
    assert result["matches"]["stamp"].get("verdict") is None


def _blank_png() -> bytes:
    image = Image.new("RGB", (400, 500), (255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


_PDFS = {
    "balance": "attestation_solde_bancaire.pdf",
    "capital": "attestation_liberation_capital.pdf",
    "labellisation": "attestation_labellisation_startup.pdf",
    "subvention": "decision_attribution_subvention.pdf",
}


def _pdf_page(doc: str) -> np.ndarray:
    raw = (GENUINE / _PDFS[doc]).read_bytes()
    _, pages, _ = load_pages(None, base64.b64encode(raw).decode())
    return pages[0]


def _stamp_verdict(store: SpecimenStore, entity: str, page: np.ndarray) -> str | None:
    row = store.check(entity, page, expect_signature=False)["matches"]["stamp"]
    return row.get("verdict")


def _paste(crop: np.ndarray) -> np.ndarray:
    page = Image.new("RGB", (900, 1200), (255, 255, 255))
    page.paste(Image.fromarray(crop), (80, 90))
    return np.asarray(page)


def _center_hole(crop: np.ndarray, side: int) -> np.ndarray:
    edited = np.asarray(crop).copy()
    half = side // 2
    cy, cx = edited.shape[0] // 2, edited.shape[1] // 2
    edited[cy - half : cy + half, cx - half : cx + half] = 255
    return edited


def test_enrolled_pdf_stays_genuine_and_a_darker_copy_does_too(tmp_path):
    store = SpecimenStore(tmp_path)
    page = _pdf_page("capital")
    assert store.enroll("capital", "stamp", page, comment="Capital")["enrolled"]
    assert _stamp_verdict(store, "capital", page) == "genuine"
    darker = np.asarray(ImageEnhance.Brightness(Image.fromarray(page)).enhance(0.75))
    assert _stamp_verdict(store, "capital", darker) == "genuine"


def test_small_rotation_and_perspective_are_not_fraudulent(tmp_path):
    store = SpecimenStore(tmp_path)
    capital = _pdf_page("capital")
    subvention = _pdf_page("subvention")
    balance = _pdf_page("balance")
    assert store.enroll("capital", "stamp", capital, comment="Capital")["enrolled"]
    assert store.enroll("subvention", "stamp", subvention, comment="Subvention")["enrolled"]
    assert store.enroll("balance", "stamp", balance, comment="Balance")["enrolled"]

    turned = np.asarray(
        Image.fromarray(capital).rotate(2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    )
    assert _stamp_verdict(store, "capital", turned) != "fraudulent"

    cases = [
        ("capital", capital, "rotate", 6),
        ("capital", capital, "rotate", 12),
        ("subvention", subvention, "rotate", 12),
        ("capital", capital, "perspective", 0.10),
        ("subvention", subvention, "perspective", 0.04),
        ("balance", balance, "perspective", 0.10),
    ]
    for entity, page, kind, amount in cases:
        image = Image.fromarray(page)
        if kind == "rotate":
            edited = image.rotate(amount, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))
        else:
            edited = _perspective(image, amount)
        verdict = _stamp_verdict(store, entity, np.asarray(edited))
        assert verdict != "fraudulent", (entity, kind, amount, verdict)


def test_a_white_hole_is_not_accepted_on_global_correlation_alone(tmp_path):
    store = SpecimenStore(tmp_path)
    for doc in ("balance", "capital", "labellisation", "subvention"):
        page = _pdf_page(doc)
        assert store.enroll(doc, "stamp", page, comment=doc)["enrolled"]
        crop = crop_array(page, find_marks(page)["stamp"])
        for side in (14, 32):
            holed = _paste(_center_hole(crop, side))
            verdict = _stamp_verdict(store, doc, holed)
            # The subvention center is blank paper, so a 14px hole removes no ink.
            if doc == "subvention" and side == 14:
                continue
            assert verdict != "genuine", (doc, side, verdict)


def test_wording_mismatch_with_a_similar_drawing_is_not_genuine(tmp_path):
    store = SpecimenStore(tmp_path)
    page = _pdf_page("labellisation")
    assert store.enroll("lab", "stamp", page, comment="Lab")["enrolled"]
    query = np.asarray(
        Image.open(STAMP_DATASET / "labellisation/pages/labellisation_0083_counterfeit.jpg").convert("RGB")
    )
    assert _stamp_verdict(store, "lab", query) != "genuine"


def test_near_black_patch_stamps_are_found_and_full_pages_stay_put():
    """A near-black oval or rectangle has no chroma for the color finder.

    The gray finder has to accept that box on a short page patch. The same
    change must keep the stamp on the four genuine PDFs in the lower part of
    the page, on the color render and on a grayscale copy. The body-text
    block is wider than the allowed gray box.
    """
    images = PACKAGE / "data" / "stamp_dataset_v3" / "dataset" / "images"
    for name in ("oval_02_gen_000.jpg", "rect_02_gen_000.jpg"):
        page = np.asarray(Image.open(images / name).convert("RGB"))
        stamp = find_marks(page)["stamp"]
        assert stamp is not None, name
        assert stamp["width"] >= 250, (name, stamp["width"])
        assert stamp["height"] >= page.shape[0] * 0.30, (name, stamp["height"])
        assert stamp["width"] / page.shape[1] <= 0.72
    for doc in ("balance", "capital", "labellisation", "subvention"):
        page = _pdf_page(doc)
        gray = np.asarray(Image.fromarray(page).convert("L").convert("RGB"))
        for image in (page, gray):
            stamp = find_marks(image)["stamp"]
            assert stamp is not None, doc
            height, width = image.shape[:2]
            assert stamp["width"] / width < 0.50, (doc, stamp["width"], width)
            assert stamp["min_y"] > height * 0.55, (doc, stamp["min_y"], height)


def test_grayscale_and_text_only_stamps_are_found():
    balance = _pdf_page("balance")
    capital = _pdf_page("capital")
    gray_balance = np.asarray(Image.fromarray(balance).convert("L").convert("RGB"))
    gray_capital = np.asarray(Image.fromarray(capital).convert("L").convert("RGB"))
    assert find_marks(gray_balance)["stamp"] is not None
    assert find_marks(gray_capital)["stamp"] is not None
    buffer = io.BytesIO()
    Image.fromarray(balance).save(buffer, format="JPEG", quality=75)
    buffer.seek(0)
    jpeg = np.asarray(Image.open(buffer).convert("RGB"))
    assert find_marks(jpeg)["stamp"] is not None
    faded = np.asarray(ImageEnhance.Brightness(Image.fromarray(balance)).enhance(1.10))
    assert find_marks(faded)["stamp"] is not None
    crop = crop_array(capital, find_marks(capital)["stamp"])
    page = Image.new("RGB", (900, 400), (255, 255, 255))
    page.paste(Image.fromarray(crop), (820, 20))
    assert find_marks(np.asarray(page))["stamp"] is not None


def _page(doc: str, name: str) -> np.ndarray:
    return np.asarray(Image.open(STAMP_DATASET / doc / "pages" / name).convert("RGB"))


def _decoded_page(doc: str, name: str) -> np.ndarray:
    """The same bytes ``POST /v1/score`` decodes for an uploaded image."""
    raw = (STAMP_DATASET / doc / "pages" / name).read_bytes()
    return decode_image(base64.b64encode(raw).decode("ascii"))


def test_labeled_structural_counterfeit_and_close_genuine_scan(tmp_path):
    """These two files are the structural cases the line-profile rule is for.

    They are a demonstration pair from the labeled set, not a claim that every
    counterfeit page separates from every genuine scan. The pages go through
    ``decode_image``, which is the upload path, so a thumbnail cannot blur a
    close genuine scan into the counterfeit band.
    """
    store = SpecimenStore(tmp_path)
    assert store.enroll("capital", "stamp", _pdf_page("capital"), comment="Capital")["enrolled"]
    assert store.enroll("balance", "stamp", _pdf_page("balance"), comment="Balance")["enrolled"]
    genuine = _decoded_page("capital", "capital_0000_reference.jpg")
    assert max(genuine.shape[:2]) > 1200
    assert _stamp_verdict(store, "capital", genuine) == "genuine"
    assert _stamp_verdict(store, "capital", _decoded_page("capital", "capital_0019_counterfeit.jpg")) == "fraudulent"
    assert _stamp_verdict(store, "balance", _decoded_page("balance", "balance_0044_counterfeit.jpg")) == "fraudulent"
    # A subtle copy stays out of the genuine band. Fraud is not required.
    subtle = _stamp_verdict(store, "capital", _decoded_page("capital", "capital_0008_counterfeit.jpg"))
    assert subtle != "genuine"


def test_a_different_organization_stays_unrecognized(tmp_path):
    store = SpecimenStore(tmp_path)
    capital = _pdf_page("capital")
    other = _pdf_page("subvention")
    assert store.enroll("capital", "stamp", capital, comment="Capital")["enrolled"]
    assert _stamp_verdict(store, "capital", other) == "unrecognized"


def test_reason_codes_name_the_observed_evidence():
    hole = {
        "ncc": 0.998,
        "local_min": 0.95,
        "quality": "ok",
        "bright_peak": 160.0,
        "dark_peak": 2.0,
    }
    decision = stamp_decision("same", hole, 0.2, False)
    assert decision == {"verdict": "fraudulent", "reason_codes": ["local_ink_anomaly"]}
    poor = stamp_decision("same", {"ncc": 0.57, "local_min": -0.39, "quality": "poor"}, 0.1, False)
    assert poor["reason_codes"] == ["poor_image_quality"]
    foreign = stamp_decision("unknown", {"ncc": 0.3, "local_min": 0.0, "quality": "ok"}, 0.1, False)
    assert foreign["reason_codes"] == ["no_matching_enrolled_identity"]
    close = stamp_decision(
        "same",
        {
            "ncc": 0.97,
            "local_min": 0.80,
            "quality": "ok",
            "bright_peak": 1.0,
            "dark_peak": 1.0,
            "row_corr": 0.985,
            "mae": 6.0,
            "low_block": 0.0,
        },
        0.01,
        False,
    )
    assert close == {"verdict": "genuine", "reason_codes": ["reference_match"]}


def test_severe_blur_is_uncertain_rather_than_a_new_organization(tmp_path):
    store = SpecimenStore(tmp_path)
    page = _pdf_page("capital")
    assert store.enroll("capital", "stamp", page, comment="Capital")["enrolled"]
    blurred = np.asarray(Image.fromarray(page).filter(ImageFilter.GaussianBlur(6)))
    stamp = store.check("capital", blurred, expect_signature=False)["matches"]["stamp"]
    assert stamp["verdict"] == "uncertain"
    assert stamp["reason_codes"] == ["poor_image_quality"]
    assert stamp["verdict"] != "fraudulent"


def test_blank_tenant_saves_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    store = SpecimenStore(tmp_path)
    page = _pdf_page("capital")
    refused = store.enroll("   ", "stamp", page, comment="no tenant")
    assert refused["enrolled"] is False
    assert refused["reason"] == "missing_tenant"
    assert store.enrolled_count() == 0
    assert "missing_tenant" in store.check("", page, expect_signature=False)["warnings"]

    client = TestClient(create_app(FraudDetectionEngine()))
    response = client.post(
        "/v1/score",
        json={
            "transaction": {**_payment(""), "receiver_id": "   "},
            "document": {
                "entity_id": "",
                "image_base64": base64.b64encode(_blank_png()).decode("ascii"),
                "expect_signature": False,
            },
        },
    )
    assert response.status_code == 200
    documents = response.json()["documents"]
    assert documents["checked"] is False
    assert "missing_tenant" in documents["warnings"]
    assert documents["approval_required"] is False
    assert not (tmp_path / "index.json").exists()
