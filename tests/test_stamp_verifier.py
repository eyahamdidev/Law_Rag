"""Supervised stamp enrollment: empty store, crop, then genuine versus fake."""

import base64
import io
import json
import zlib
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from fraud_detection.api.app import create_app
from fraud_detection.documents.stamp_content import content_relation
from fraud_detection.documents.specimens import SpecimenStore
from fraud_detection.documents.stamp_verifier import StampVerifier
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.paths import EVAL, GENUINE, STAMP_DATASET, STAMP_VERIFIER


def _held_out(name: str) -> bool:
    return zlib.crc32(name.encode("utf-8")) % 5 == 0


def _png_page(crop_path: Path) -> str:
    stamp = Image.open(crop_path).convert("RGB")
    scale = 0.55
    resized = stamp.resize(
        (max(1, int(stamp.width * scale)), max(1, int(stamp.height * scale))),
        Image.Resampling.BILINEAR,
    )
    page = Image.new("RGB", (900, 1200), (255, 255, 255))
    page.paste(resized, (900 - resized.width - 70, 1200 - resized.height - 70))
    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _payment() -> dict:
    return {
        "transaction_id": "pay-stamp",
        "timestamp": "2024-11-18T11:00:00",
        "amount": 125.0,
        "currency": "EUR",
        "transaction_type": "transfer",
        "sender_id": "fr-sender",
        "receiver_id": "supplier-9",
        "country_from": "FR",
        "country_to": "FR",
    }


def test_stamp_wording_separates_a_different_organization_from_the_same_one():
    startup = "comite ministre nov innovations startup label"
    bank = "banque publique fev tunis specimen"
    same_bank = "banque publique fev tunis 1745039"
    assert content_relation(startup, bank) == "different"
    assert content_relation(bank, same_bank) == "same"
    assert content_relation("", "banque") == "unknown"


def test_fresh_store_has_no_enrolled_stamp(tmp_path):
    store = SpecimenStore(tmp_path)
    assert store.enrolled_count() == 0
    assert not (tmp_path / "index.json").exists()


def test_shipped_enrollment_store_is_empty():
    index = GENUINE.parent / "specimens" / "index.json"
    assert not index.exists()
    readme = (GENUINE.parent / "specimens" / "README.md").read_text(encoding="utf-8")
    assert "starts empty" in readme


def test_supervised_metrics_are_recorded():
    metrics = json.loads((EVAL / "stamp_verifier_metrics.json").read_text(encoding="utf-8"))
    assert metrics["method"] == "supervised"
    assert metrics["unsupervised_used"] is False
    assert metrics["validation"]["pr_auc"] >= 0.75
    assert metrics["validation"]["fake_recall"] >= 0.70
    assert metrics["validation"]["genuine_recall"] >= 0.75
    verifier = StampVerifier.load(STAMP_VERIFIER)
    assert verifier.method == "supervised"
    assert verifier.model is not None


def test_enroll_saves_the_crop_and_comment(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    crops = sorted((STAMP_DATASET / "labellisation" / "stamp_crops").glob("*_reference.jpg"))
    image = _png_page(crops[0])
    enrolled = client.post(
        "/v1/documents/enroll",
        json={
            "entity_id": "supplier-9",
            "kind": "stamp",
            "image_base64": image,
            "comment": "Cachet officiel du comité",
        },
    )
    assert enrolled.status_code == 200
    body = enrolled.json()
    assert body["enrolled"] is True
    assert body["comment"] == "Cachet officiel du comité"
    assert body["crop_base64"]
    assert (tmp_path / f"{body['specimen_id']}.png").is_file()
    saved = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert saved["specimens"][0]["comment"] == "Cachet officiel du comité"


def _stamp_mark(client: TestClient, image: str, secret: str | None = None) -> dict:
    document = {"image_base64": image, "expect_signature": False}
    if secret:
        document["tenant_secret"] = secret
    response = client.post(
        "/v1/score",
        json={
            "transaction": _payment(),
            "document": document,
        },
    )
    assert response.status_code == 200
    return next(item for item in response.json()["documents"]["marks"] if item["kind"] == "stamp")


def test_score_api_judges_later_documents_against_the_enrolled_stamp(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    capital = STAMP_DATASET / "capital" / "stamp_crops"
    references = [path for path in sorted(capital.glob("*_reference.jpg")) if _held_out(path.name)]
    counterfeits = [path for path in sorted(capital.glob("*_counterfeit.jpg")) if _held_out(path.name)]
    other_stamp = next((STAMP_DATASET / "subvention" / "stamp_crops").glob("*_reference.jpg"))
    enrolled_page = _png_page(references[0])
    first = client.post(
        "/v1/score",
        json={
            "transaction": _payment(),
            "document": {
                "image_base64": enrolled_page,
                "expect_signature": False,
                "comment": "Cachet BPAE enrôlé",
            },
        },
    )
    stamp = next(item for item in first.json()["documents"]["marks"] if item["kind"] == "stamp")
    assert stamp["status"] == "awaiting_approval"
    assert stamp["crop_base64"]
    assert client.get("/health").json()["enrolled_specimens"] == 0
    approved = client.post(
        "/v1/documents/decide",
        json={"proposal_id": stamp["proposal_id"], "approve": True, "comment": "Cachet BPAE enrôlé"},
    )
    assert approved.json()["enrolled"] is True
    secret = approved.json()["tenant_secret"]
    assert secret
    assert approved.json()["comment"] == "Cachet BPAE enrôlé"

    same = _stamp_mark(client, enrolled_page, secret)
    assert same["status"] == "match"
    assert same["verdict"] == "genuine"
    assert same["comment"] == "Cachet BPAE enrôlé"

    fraud_marks = [
        _stamp_mark(client, _png_page(path), secret)
        for path in counterfeits[:5]
    ]
    # A low global score is not enough to call a stamp forged. These copies
    # must still be refused: uncertain, unrecognized, or fraudulent.
    assert fraud_marks
    assert all(mark["verdict"] in {"fraudulent", "uncertain", "unrecognized"} for mark in fraud_marks)
    assert all(mark["verdict"] != "genuine" for mark in fraud_marks)
    refused = [mark for mark in fraud_marks if mark["verdict"] in {"fraudulent", "uncertain"}]
    assert refused
    assert refused[0]["proposal_id"] is None
    assert refused[0]["question"] is None or refused[0]["verdict"] == "uncertain"

    different = _stamp_mark(client, _png_page(other_stamp), secret)
    assert different["verdict"] == "unrecognized"
    assert different["status"] == "unrecognized"
    assert different["question"]
    assert different["proposal_id"]
    enrolled_other = client.post(
        "/v1/documents/decide",
        json={
            "proposal_id": different["proposal_id"],
            "approve": True,
            "comment": "Second genuine stamp",
            "tenant_secret": secret,
        },
    )
    assert enrolled_other.json()["enrolled"] is True
    assert _stamp_mark(client, _png_page(other_stamp), secret)["verdict"] == "genuine"
    assert _stamp_mark(client, enrolled_page, secret)["verdict"] == "genuine"

    fake_scores = [_stamp_mark(client, _png_page(path), secret)["genuine_probability"] for path in counterfeits[:5]]
    assert min(fake_scores) < 0.15


def test_genuine_reference_pdf_crops_a_stamp_on_a_fresh_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    client = TestClient(create_app(FraudDetectionEngine()))
    pdf = (GENUINE / "attestation_labellisation_startup.pdf").read_bytes()
    encoded = base64.b64encode(pdf).decode("ascii")
    first = client.post(
        "/v1/score",
        json={
            "transaction": _payment(),
            "document": {"pdf_base64": encoded, "filename": "label.pdf", "expect_signature": False},
        },
    )
    body = first.json()
    stamp = next(item for item in body["documents"]["marks"] if item["kind"] == "stamp")
    assert stamp["status"] == "awaiting_approval"
    crop = Image.open(io.BytesIO(base64.b64decode(stamp["crop_base64"])))
    assert crop.size[0] > 40 and crop.size[1] > 40
    approved = client.post(
        "/v1/documents/decide",
        json={"proposal_id": stamp["proposal_id"], "approve": True, "comment": "Cachet labellisation"},
    )
    assert approved.json()["comment"] == "Cachet labellisation"
    secret = approved.json()["tenant_secret"]
    second = client.post(
        "/v1/score",
        json={
            "transaction": _payment(),
            "document": {
                "pdf_base64": encoded,
                "filename": "label.pdf",
                "expect_signature": False,
                "tenant_secret": secret,
            },
        },
    )
    again = next(item for item in second.json()["documents"]["marks"] if item["kind"] == "stamp")
    assert again["status"] == "match"
    assert again["verdict"] == "genuine"
    assert again["comment"] == "Cachet labellisation"
