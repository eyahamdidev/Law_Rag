"""Handoff checks: routing, domestic vs cross-border, and unseen payment shapes."""

from datetime import datetime, timedelta

import inspect

import pytest
from fastapi.testclient import TestClient

import fraud_detection.fraud_client as fraud_client
from fraud_detection.api.app import create_app
from fraud_detection.fraud_client import score_transaction
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.models.supervised import eligible_supervised_types
from fraud_detection.paths import ARTIFACTS
from fraud_detection.schema import Decision, Transaction


def _tx(**fields) -> Transaction:
    base = {
        "transaction_id": "tx",
        "timestamp": datetime(2024, 11, 4, 14, 0),
        "amount": 120.0,
        "currency": "EUR",
        "transaction_type": "transfer",
        "sender_id": "sender",
        "receiver_id": "shop",
        "country_from": "FR",
        "country_to": "FR",
    }
    base.update(fields)
    return Transaction(**base)


def test_gift_card_barter_is_not_a_card_payment():
    gift = _tx(transaction_id="gift", transaction_type="gift_card_barter", channel="qr_kiosk", currency="JPY")
    assert eligible_supervised_types(gift) == frozenset()
    credit = _tx(transaction_id="credit", transaction_type="credit card", channel=None)
    assert eligible_supervised_types(credit) == frozenset({"CARD_FRAUD"})
    debit = _tx(transaction_id="debit", transaction_type="debit_card")
    assert eligible_supervised_types(debit) == frozenset({"CARD_FRAUD"})


def test_domestic_new_beneficiary_is_not_treated_as_foreign():
    history = [
        _tx(
            transaction_id=f"h-{index}",
            timestamp=datetime(2024, 10, 1, 11, 0) + timedelta(weeks=index),
            amount=120,
            receiver_id="usual-shop",
        )
        for index in range(6)
    ]
    domestic = _tx(
        transaction_id="new-fr",
        timestamp=datetime(2024, 11, 18, 11, 0),
        amount=9000,
        receiver_id="new-shop",
        country_from="FR",
        country_to="FR",
    )
    result = FraudDetectionEngine().score(domestic, history)
    hit = next(item for item in result.signals if item.signal == "new_counterparty")
    assert hit.severity == "medium"
    assert result.decision != Decision.HIGH_RISK
    assert result.risk_score < 75

    cross = domestic.model_copy(
        update={"transaction_id": "new-ly", "country_from": "TN", "country_to": "LY", "currency": "TND"}
    )
    foreign = FraudDetectionEngine().score(cross, history)
    foreign_hit = next(item for item in foreign.signals if item.signal == "new_counterparty")
    assert foreign_hit.severity == "high"
    assert foreign.decision == Decision.HIGH_RISK
    assert foreign.tunisia.tunisia_score is None


def test_unknown_request_fields_are_ignored_and_history_is_optional():
    client = TestClient(create_app(FraudDetectionEngine()))
    response = client.post(
        "/v1/score",
        json={
            "transaction": {"amount": 30, "sender_account": "a", "beneficiary_account": "b", "unused_column": "x"},
            "orchestrator_trace": "abc",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["graph_status"] == "insufficient_history"
    assert body["tunisia"]["tunisia_score"] is None
    assert body["risk_score"] == client.post(
        "/v1/score",
        json={"transaction": {"amount": 30, "sender_account": "a", "beneficiary_account": "b"}},
    ).json()["risk_score"]


def test_http_client_calls_score_without_model_imports():
    source = inspect.getsource(fraud_client)
    assert "fraud_detection.models" not in source
    assert "lightgbm" not in source
    assert "joblib" not in source

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"risk_score": 4, "risk_level": "LOW_RISK"}

    class _Client:
        def __init__(self) -> None:
            self.url = ""
            self.payload: dict = {}

        def post(self, url: str, json: dict | None = None) -> _Response:
            self.url = url
            self.payload = json or {}
            return _Response()

        def close(self) -> None:
            return None

    client = _Client()
    body = score_transaction(
        "http://fraud/",
        {"amount": 15, "currency": "EUR", "sender_id": "s", "receiver_id": "r"},
        client=client,
    )
    assert client.url == "http://fraud/v1/score"
    assert "history" not in client.payload
    assert "entities" not in client.payload
    assert body["risk_score"] == 4
    scored = score_transaction(
        "http://fraud",
        {"amount": 15},
        history=[{"transaction_id": "old"}],
        entities=[{"entity_id": "s", "name": "Shop"}],
        client=client,
    )
    assert scored["risk_level"] == "LOW_RISK"
    assert client.payload["history"][0]["transaction_id"] == "old"
    assert client.payload["entities"][0]["name"] == "Shop"


@pytest.mark.skipif(
    not (ARTIFACTS / "supervised.joblib").exists(),
    reason="trained artifacts are produced by python -m fraud_detection train",
)
def test_unseen_shapes_stay_finite_and_in_domain():
    from fraud_detection.api.app import engine_from_env

    engine = engine_from_env()
    start = datetime(2024, 11, 4, 14, 0)
    history = [
        _tx(
            transaction_id=f"week-{index}",
            timestamp=start - timedelta(weeks=6 - index),
            amount=120,
            receiver_id="usual-shop",
        )
        for index in range(6)
    ]
    recurring = engine.score(_tx(transaction_id="recurring", timestamp=start, amount=125), history)
    assert recurring.decision == Decision.LOW_RISK
    assert recurring.risk_score < 45
    assert "CARD_FRAUD" not in recurring.label_types

    large = engine.score(
        _tx(transaction_id="large", timestamp=start, amount=8000, receiver_id="usual-shop"),
        history,
    )
    assert large.decision != Decision.HIGH_RISK
    assert "new_counterparty" not in large.fraud_types

    invoice_prior = _tx(
        transaction_id="inv-1",
        timestamp=start - timedelta(hours=5),
        amount=4200,
        invoice_id="FAC-9",
        receiver_id="supplier",
    )
    invoice = engine.score(
        invoice_prior.model_copy(update={"transaction_id": "inv-2", "timestamp": start}),
        [invoice_prior],
    )
    assert invoice.decision == Decision.HIGH_RISK
    assert "INVOICE_FRAUD" in invoice.label_types
    assert "AML_LAUNDERING" not in invoice.label_types

    gift = engine.score(
        _tx(
            transaction_id="gift",
            transaction_type="gift_card_barter",
            channel="qr_kiosk",
            currency="JPY",
            amount=40,
        ),
        [],
    )
    assert "CARD_FRAUD" not in gift.model_scores.supervised_by_type
    assert gift.decision != Decision.HIGH_RISK
    assert gift.risk_score == engine.score(
        _tx(
            transaction_id="gift",
            transaction_type="gift_card_barter",
            channel="qr_kiosk",
            currency="JPY",
            amount=40,
        ),
        [],
    ).risk_score
