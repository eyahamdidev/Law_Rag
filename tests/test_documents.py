import base64
import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from fraud_detection.api.app import create_app
from fraud_detection.documents.specimens import SpecimenStore, decode_image
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.paths import GENUINE


def _png(draw) -> str:
    image = Image.new("L", (400, 520), 255)
    draw(ImageDraw.Draw(image))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _stamp_and_signature(draw: ImageDraw.ImageDraw) -> None:
    draw.ellipse((280, 40, 360, 120), outline=0, width=6)
    draw.line((40, 450, 180, 430), fill=0, width=3)
    draw.line((180, 430, 240, 460), fill=0, width=3)
    draw.line((60, 470, 200, 455), fill=0, width=2)


def _stamp_only(draw: ImageDraw.ImageDraw) -> None:
    draw.ellipse((280, 40, 360, 120), outline=0, width=6)


def _other_stamp_only(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((280, 40, 360, 120), outline=0, width=8)


def _larger_stamp(draw: ImageDraw.ImageDraw) -> None:
    draw.ellipse((276, 36, 364, 124), outline=0, width=6)
    draw.line((40, 450, 180, 430), fill=0, width=3)
    draw.line((180, 430, 240, 460), fill=0, width=3)
    draw.line((60, 470, 200, 455), fill=0, width=2)


def _other_stamp(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((280, 40, 360, 120), outline=0, width=8)
    draw.line((40, 450, 180, 430), fill=0, width=3)
    draw.line((180, 430, 240, 460), fill=0, width=3)
    draw.line((60, 470, 200, 455), fill=0, width=2)


def _signature_only(draw: ImageDraw.ImageDraw) -> None:
    draw.line((40, 450, 180, 430), fill=0, width=3)
    draw.line((180, 430, 240, 460), fill=0, width=3)


def test_missing_stamp_is_a_warning(tmp_path):
    store = SpecimenStore(tmp_path)
    gray = decode_image(_png(_signature_only))
    result = store.check("supplier-1", gray)
    assert result["stamp_present"] is False
    assert result["signature_present"] is True
    assert "missing_stamp" in result["warnings"]
    assert result["matches"]["stamp"]["status"] == "missing"
    assert result["proof"] is False


def test_enrolled_stamp_matches_a_later_copy_and_rejects_a_different_drawing(tmp_path):
    store = SpecimenStore(tmp_path)
    original = decode_image(_png(_stamp_and_signature))
    enrolled = store.enroll("supplier-1", "stamp", original)
    assert enrolled["enrolled"] is True

    same = store.check("supplier-1", original, expect_signature=False)
    assert same["matches"]["stamp"]["status"] == "match"
    assert same["matches"]["stamp"]["similarity"] >= 0.84

    other = store.check("supplier-1", decode_image(_png(_other_stamp)), expect_signature=False)
    assert other["stamp_present"] is True
    assert other["matches"]["stamp"]["status"] == "unrecognized"
    assert other["matches"]["stamp"]["verdict"] == "unrecognized"
    assert other["matches"]["stamp"]["question"]
    assert "stamp_unrecognized" in other["warnings"]

    larger = store.check("supplier-1", decode_image(_png(_larger_stamp)), expect_signature=False)
    # A uniformly larger copy of the same drawing is a capture-scale change.
    # It must not be enrolled as a new stamp and must not be called a different organization.
    assert larger["matches"]["stamp"]["verdict"] in {"genuine", "uncertain"}
    assert larger["matches"]["stamp"]["proposal_id"] is None
    assert "stamp_unrecognized" not in larger["warnings"]


def _payment(receiver_id: str = "supplier-9") -> dict:
    return {
        "transaction_id": "pay-100",
        "timestamp": "2024-11-18T11:00:00",
        "amount": 125.0,
        "currency": "EUR",
        "transaction_type": "transfer",
        "sender_id": "fr-sender",
        "receiver_id": receiver_id,
        "country_from": "FR",
        "country_to": "FR",
    }


def _mark(body: dict, kind: str) -> dict:
    return next(item for item in body["documents"]["marks"] if item["kind"] == kind)


def test_score_without_a_file_does_not_ask_to_save(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    response = client.post("/v1/score", json={"transaction": _payment()})
    assert response.status_code == 200
    body = response.json()
    assert body["documents"] is None
    assert body["decision"] == "LOW_RISK"
    assert "document_missing_stamp" not in body["fraud_types"]


def test_score_crops_a_stamp_and_saves_it_only_after_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    image = _png(_stamp_only)
    first = client.post(
        "/v1/score",
        json={"transaction": _payment(), "document": {"image_base64": image, "expect_signature": False}},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["documents"]["approval_required"] is True
    assert body["documents"]["checked"] is True
    stamp = _mark(body, "stamp")
    assert stamp["status"] == "awaiting_approval"
    assert stamp["question"]
    assert stamp["crop_base64"]
    assert "waiting for approval" in body["explanation"]
    assert list(tmp_path.glob("*.npy"))
    assert not list(tmp_path.glob("index.json")) or "specimens" not in (tmp_path / "index.json").read_text()

    declined = client.post("/v1/documents/decide", json={"proposal_id": stamp["proposal_id"], "approve": False})
    assert declined.json()["enrolled"] is False
    assert not (tmp_path / "index.json").exists()

    again = client.post(
        "/v1/score",
        json={"transaction": _payment(), "document": {"image_base64": image, "expect_signature": False}},
    )
    proposal_id = _mark(again.json(), "stamp")["proposal_id"]
    assert proposal_id != stamp["proposal_id"]
    approved = client.post("/v1/documents/decide", json={"proposal_id": proposal_id, "approve": True})
    assert approved.status_code == 200
    secret = approved.json()["tenant_secret"]
    assert approved.json()["enrolled"] is True
    locked = client.post("/v1/documents/decide", json={"proposal_id": proposal_id, "approve": True})
    assert locked.json()["reason"] == "tenant_unauthorized"
    repeat = client.post(
        "/v1/documents/decide",
        json={"proposal_id": proposal_id, "approve": True, "tenant_secret": secret},
    )
    assert repeat.json()["reason"] == "already_decided"

    matched = client.post(
        "/v1/score",
        json={"transaction": _payment(), "document": {"image_base64": image, "expect_signature": False, "tenant_secret": secret}},
    )
    saved = matched.json()
    assert _mark(saved, "stamp")["status"] == "match"
    assert saved["documents"]["approval_required"] is False
    assert "document_stamp_mismatch" not in saved["fraud_types"]

    forged = client.post(
        "/v1/score",
        json={
            "transaction": _payment(),
            "document": {"image_base64": _png(_other_stamp_only), "expect_signature": False, "tenant_secret": secret},
        },
    )
    warning = forged.json()
    unknown = _mark(warning, "stamp")
    assert unknown["status"] == "unrecognized"
    assert unknown["verdict"] == "unrecognized"
    assert unknown["question"]
    assert unknown["proposal_id"]
    assert "document_stamp_unrecognized" in warning["fraud_types"]
    assert "document_stamp_mismatch" not in warning["fraud_types"]
    assert warning["requires_human_review"] is True
    assert warning["risk_score"] >= 60
    assert warning["documents"]["approval_required"] is True
    enrolled_new = client.post(
        "/v1/documents/decide",
        json={
            "proposal_id": unknown["proposal_id"],
            "approve": True,
            "comment": "Second genuine stamp",
            "tenant_secret": secret,
        },
    )
    assert enrolled_new.json()["enrolled"] is True
    rectangle = client.post(
        "/v1/score",
        json={
            "transaction": _payment(),
            "document": {"image_base64": _png(_other_stamp_only), "expect_signature": False, "tenant_secret": secret},
        },
    )
    assert _mark(rectangle.json(), "stamp")["status"] == "match"
    assert _mark(rectangle.json(), "stamp")["verdict"] == "genuine"
    original_again = client.post(
        "/v1/score",
        json={"transaction": _payment(), "document": {"image_base64": image, "expect_signature": False, "tenant_secret": secret}},
    )
    assert _mark(original_again.json(), "stamp")["verdict"] == "genuine"


def test_score_warns_when_the_uploaded_page_has_no_stamp(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    response = client.post(
        "/v1/score",
        json={"transaction": _payment(), "document": {"image_base64": _png(_signature_only)}},
    )
    body = response.json()
    assert "missing_stamp" in body["documents"]["warnings"]
    assert "document_missing_stamp" in body["fraud_types"]
    assert body["requires_human_review"] is True
    assert body["risk_score"] >= 45
    assert body["decision"] == "MEDIUM_RISK"


def test_score_reads_a_pdf_and_crops_the_stamp(tmp_path, monkeypatch):
    pymupdf = __import__("pymupdf")
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    png = base64.b64decode(_png(_stamp_and_signature))
    document = pymupdf.open()
    page = document.new_page(width=400, height=520)
    page.insert_text((40, 40), "Invoice FAC-9 for supplier-9")
    page.insert_image(pymupdf.Rect(0, 60, 400, 520), stream=png)
    pdf_base64 = base64.b64encode(document.tobytes()).decode("ascii")
    document.close()

    response = client.post(
        "/v1/score",
        json={
            "transaction": _payment(),
            "document": {"pdf_base64": pdf_base64, "filename": "invoice.pdf", "expect_signature": False},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["documents"]["source"] == "pdf"
    assert body["documents"]["pages"] == 1
    assert "Invoice FAC-9" in body["documents"]["text_excerpt"]
    assert _mark(body, "stamp")["status"] == "awaiting_approval"
    assert _mark(body, "stamp")["crop_base64"]


def test_api_enroll_and_check_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    image = _png(_stamp_and_signature)
    enrolled = client.post(
        "/v1/documents/enroll",
        json={"entity_id": "supplier-9", "kind": "stamp", "image_base64": image},
    )
    assert enrolled.status_code == 200
    assert enrolled.json()["enrolled"] is True
    secret = enrolled.json()["tenant_secret"]
    checked = client.post(
        "/v1/documents/check",
        json={"entity_id": "supplier-9", "image_base64": image, "expect_signature": False, "tenant_secret": secret},
    )
    assert checked.status_code == 200
    body = checked.json()
    assert body["matches"]["stamp"]["status"] == "match"
    assert body["proof"] is False
    blocked = client.post(
        "/v1/documents/check",
        json={"entity_id": "supplier-9", "image_base64": image, "expect_signature": False},
    )
    assert "tenant_unauthorized" in blocked.json()["warnings"]
    assert blocked.json()["matches"] == {}


def test_genuine_pdfs_live_with_the_project_data():
    names = sorted(path.name for path in GENUINE.glob("*.pdf"))
    assert names == [
        "attestation_labellisation_startup.pdf",
        "attestation_liberation_capital.pdf",
        "attestation_solde_bancaire.pdf",
        "decision_attribution_subvention.pdf",
    ]
    assert (GENUINE / "manifest.json").is_file()
