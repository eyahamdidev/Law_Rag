"""Review tiers and tenant secrets. These tests do not score stamp images."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from fraud_detection.api.app import create_app
from fraud_detection.documents.intake import pdf_clues
from fraud_detection.documents.specimens import SpecimenStore, _note_inserted_image
from fraud_detection.documents.stamp_alignment import review_triage
from fraud_detection.inference.pipeline import FraudDetectionEngine


def test_review_triage_queues_specific_evidence_and_not_a_close_match():
    assert review_triage("genuine", ["reference_match"]) == {
        "review_recommended": False,
        "risk_level": "low",
    }
    assert review_triage("fraudulent", ["local_ink_anomaly"]) == {
        "review_recommended": True,
        "risk_level": "high",
    }
    assert review_triage("uncertain", ["text_mismatch"])["risk_level"] == "medium"
    assert review_triage("uncertain", ["possible_inserted_image"])["risk_level"] == "high"
    assert review_triage("uncertain", ["insufficient_evidence"]) == {
        "review_recommended": True,
        "risk_level": "medium",
    }
    assert review_triage("unrecognized", ["no_matching_enrolled_identity"])["risk_level"] == "medium"
    assert review_triage("missing", ["missing_stamp"])["risk_level"] == "medium"
    # A high review tier is not a fraudulent verdict.
    queued = review_triage("uncertain", ["text_mismatch"])
    assert queued["review_recommended"] is True
    assert queued.get("verdict") is None


def test_an_image_object_is_a_clue_only_when_the_verdict_is_already_open():
    genuine = {"kind": "stamp", "verdict": "genuine", "reason_codes": ["reference_match"], "evidence": {}}
    uncertain = {"kind": "stamp", "verdict": "uncertain", "reason_codes": ["insufficient_evidence"], "evidence": {}}
    _note_inserted_image(
        [genuine, uncertain],
        {"available": True, "image_objects": 1, "drawings": 4},
    )
    assert genuine["reason_codes"] == ["reference_match"]
    assert "possible_inserted_image" in uncertain["reason_codes"]
    assert uncertain["evidence"]["possible_inserted_image"] == "clue_not_proof"
    assert uncertain["risk_level"] == "high"
    assert uncertain["verdict"] == "uncertain"


def test_jpeg_pages_have_no_pdf_structure_clues():
    clues = pdf_clues(None)
    assert clues["available"] is False
    assert clues["reason"] == "not_a_pdf"
    assert clues["exact_stamp_copy_from_crop_alone"] is False


def _lock(root, org: str, secret: str, proposal: str | None = None) -> SpecimenStore:
    store = SpecimenStore(root)
    (root / "index.json").write_text(
        json.dumps({"specimens": [{"specimen_id": "spec-" + org, "entity_id": org, "kind": "stamp"}]}) + "\n",
        encoding="utf-8",
    )
    (root / "tenants.json").write_text(json.dumps({"secrets": {org: secret}}) + "\n", encoding="utf-8")
    if proposal:
        (root / "proposals.json").write_text(
            json.dumps(
                {
                    "proposals": [
                        {
                            "proposal_id": proposal,
                            "entity_id": org,
                            "kind": "stamp",
                            "status": "pending",
                            "comment": "pending",
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
    return store


def test_secret_does_not_open_another_organization(tmp_path):
    store = _lock(tmp_path, "org-a", "secret-a")
    (tmp_path / "tenants.json").write_text(
        json.dumps({"secrets": {"org-a": "secret-a", "org-b": "secret-b"}}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "specimens": [
                    {"specimen_id": "spec-a", "entity_id": "org-a", "kind": "stamp"},
                    {"specimen_id": "spec-b", "entity_id": "org-b", "kind": "stamp"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert store.tenant_authorized("org-a", "secret-a") is True
    assert store.tenant_authorized("org-a", "secret-b") is False
    assert store.tenant_authorized("org-a", None) is False
    assert store.tenant_authorized("   ", None) is True
    assert store.tenant_is_locked("org-b") is True
    assert store.tenant_is_locked("nobody") is False


def test_decide_and_decline_require_the_secret_after_enrollment(tmp_path):
    store = _lock(tmp_path, "org-a", "secret-a", proposal="prop-1")
    blocked = store.decide("prop-1", True)
    assert blocked["reason"] == "tenant_unauthorized"
    assert blocked["enrolled"] is False
    wrong = store.decide("prop-1", False, tenant_secret="secret-b")
    assert wrong["reason"] == "tenant_unauthorized"
    still = json.loads((tmp_path / "proposals.json").read_text(encoding="utf-8"))
    assert still["proposals"][0]["status"] == "pending"
    declined = store.decide("prop-1", False, tenant_secret="secret-a")
    assert declined["decision"] == "declined"
    assert declined["enrolled"] is False
    again = store.decide("prop-1", True, tenant_secret="secret-a")
    assert again["reason"] == "already_decided"
    assert again["enrolled"] is False
    assert store.enrolled_count() == 1


def test_first_proposal_can_still_be_declined_before_a_secret_exists(tmp_path):
    store = SpecimenStore(tmp_path)
    (tmp_path / "proposals.json").write_text(
        json.dumps(
            {
                "proposals": [
                    {
                        "proposal_id": "first",
                        "entity_id": "new-org",
                        "kind": "stamp",
                        "status": "pending",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    declined = store.decide("first", False)
    assert declined["decision"] == "declined"
    assert store.enrolled_count() == 0


def test_api_refuses_a_locked_organization_without_its_own_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_SPECIMEN_DIR", str(tmp_path))
    _lock(tmp_path, "org-a", "secret-a", proposal="prop-1")
    client = TestClient(create_app(FraudDetectionEngine()))
    missing = client.post(
        "/v1/documents/check",
        json={"entity_id": "   ", "image_base64": "abcd"},
    )
    assert missing.json()["warnings"] == ["missing_tenant"]
    blocked = client.post(
        "/v1/documents/check",
        json={"entity_id": "org-a", "image_base64": "abcd", "tenant_secret": "secret-b"},
    )
    body = blocked.json()
    assert body["warnings"] == ["tenant_unauthorized"]
    assert body["matches"] == {}
    enroll = client.post(
        "/v1/documents/enroll",
        json={"entity_id": "org-a", "kind": "stamp", "image_base64": "abcd"},
    )
    assert enroll.json()["reason"] == "tenant_unauthorized"
    decided = client.post("/v1/documents/decide", json={"proposal_id": "prop-1", "approve": True})
    assert decided.json()["reason"] == "tenant_unauthorized"
    assert json.loads((tmp_path / "proposals.json").read_text(encoding="utf-8"))["proposals"][0]["status"] == "pending"
