"""Contract tests for the standalone P3 aid service."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.aid.app import app


client = TestClient(app)


def test_health_and_meta_contract():
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "aid"

    meta = client.get("/v1/meta")
    assert meta.status_code == 200
    assert meta.json()["contract_version"] == "v1"
    assert meta.json()["catalog_programs"] >= 5


def test_run_returns_frozen_shape_and_rule_trace():
    response = client.post(
        "/v1/run",
        json={
            "request_id": "test-1",
            "question": "Je crée une entreprise industrielle avec un prêt de 200000 DT.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "abstain"}
    assert {"request_id", "answer", "citations", "signals", "artifacts", "trace", "latency_ms"} <= body.keys()
    assert any(signal["type"] == "eligibility" for signal in body["signals"])


def test_run_hands_legal_questions_to_law():
    response = client.post(
        "/v1/run",
        json={"question": "Que dit l'article 6 de la loi 2016-71 ?"},
    )
    assert response.status_code == 200
    assert response.json()["handoff"]["to"] == "law"

