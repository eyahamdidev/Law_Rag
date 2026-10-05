"""Scaffold contracts: routing, corpus counts, aid filter, fraud hash."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health_and_modules():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    modules = client.get("/api/modules")
    ids = {item["id"] for item in modules.json()}
    assert {"router", "fraud", "aid", "verifier"} <= ids


def test_corpus_sees_local_folders():
    body = client.get("/api/corpus").json()
    assert body["law"]["pdf_count"] > 0
    assert body["aid"]["file_count"] > 0
    assert body["fraud"]["exists"] is True


def test_chat_routes_tax_and_abstains():
    response = client.post(
        "/api/chat",
        json={"question": "Quel est le taux de TVA sur une prestation ?"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["intent"] == "rag"
    assert "tax" in body["domains"]
    assert body["abstained"] is True
    assert body["citations"] == []


def test_chat_routes_fraud_and_aid():
    fraud = client.post(
        "/api/chat",
        json={"question": "Cette facture fictive est-elle une fraude ?"},
    ).json()
    assert fraud["intent"] == "fraud"
    aid = client.post(
        "/api/chat",
        json={"question": "Quels documents BFPME pour une subvention ?"},
    ).json()
    assert aid["intent"] == "aid"


def test_aid_creation_lists_bfpme():
    body = client.post("/api/aid/match", json={"stage": "creation", "need": "financing"}).json()
    ids = {item["id"] for item in body["programs"]}
    assert "bfpme-creation" in ids
    assert "bfpme-extension" not in ids


def test_fraud_upload_hashes_without_a_risk_level():
    response = client.post(
        "/api/fraud/analyze",
        files={"file": ("facture.txt", b"total 1000", "text/plain")},
        data={"document_type": "invoice"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["risk_level"] == "unknown"
    assert body["signals"] == []
    assert len(body["document_hash"]) == 64
