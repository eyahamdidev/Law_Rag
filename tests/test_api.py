from fastapi.testclient import TestClient

from fraud_detection.api.app import create_app
from fraud_detection.inference.pipeline import FraudDetectionEngine


def test_health_and_score_round_trip():
    client = TestClient(create_app(FraudDetectionEngine()))
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["layers"] == ["rules", "supervised", "anomaly", "graph", "entity_intelligence"]

    payload = {
        "transaction": {
            "transaction_id": "inv-2",
            "timestamp": "2024-05-01T11:00:00",
            "amount": 1000,
            "currency": "TND",
            "sender_id": "A",
            "receiver_id": "B",
            "invoice_id": "FAC-1",
            "country_from": "TN",
            "country_to": "TN",
        },
        "history": [
            {
                "transaction_id": "inv-1",
                "timestamp": "2024-05-01T09:00:00",
                "amount": 1000,
                "currency": "TND",
                "sender_id": "A",
                "receiver_id": "B",
                "invoice_id": "FAC-1",
                "country_from": "TN",
                "country_to": "TN",
            }
        ],
    }
    response = client.post("/v1/score", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "HIGH_RISK"
    assert body["requires_human_review"] is True
    assert "duplicate_invoice" in body["fraud_types"]
    assert "INVOICE_FRAUD" in body["label_types"]
    assert "risk_score" in body
    assert {"supervised", "anomaly", "graph"} <= set(body["model_scores"])
    assert body["model_scores"]["supervised"] is None
    assert "explanation" in body
