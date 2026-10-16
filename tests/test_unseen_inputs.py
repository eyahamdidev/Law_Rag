import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fraud_detection.api.app import create_app
from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.models.supervised import SupervisedDetector, eligible_supervised_types
from fraud_detection.normalize import normalize_transaction_payload
from fraud_detection.paths import ARTIFACTS
from fraud_detection.schema import Decision, SanctionsEntry, Transaction


def test_aliases_map_onto_canonical_fields():
    payload = normalize_transaction_payload(
        {
            "transaction_amount": "1,250.50",
            "source_account": "ACCT-9",
            "beneficiary": "ACCT-2",
            "currency_code": "eur",
            "transaction_time": "2024-06-01T15:30:00",
            "payment_type": "WIRE",
            "V1": 0.1,
            "V2": -0.2,
        }
    )
    assert payload["amount"] == 1250.50
    assert payload["sender_id"] == "ACCT-9"
    assert payload["receiver_id"] == "ACCT-2"
    assert payload["currency"] == "EUR"
    assert payload["transaction_type"] == "wire"
    assert payload["metadata"]["pca"]["V1"] == 0.1
    assert eligible_supervised_types(Transaction.model_validate(payload)) == frozenset({"AML_LAUNDERING"})


def test_missing_fields_do_not_crash_and_are_low_coverage():
    client = TestClient(create_app(FraudDetectionEngine()))
    response = client.post("/v1/score", json={"transaction": {"amount": 20, "currency": "dinars"}})
    assert response.status_code == 200
    body = response.json()
    assert body["data_coverage"] == "LOW"
    assert body["model_confidence"] <= 0.35
    assert body["graph_status"] == "insufficient_history"
    assert "CARD_FRAUD" not in body["label_types"]
    assert body["model_scores"]["supervised"] is None
    json.dumps(body)


def test_unknown_schema_scores_without_a_specialist_label():
    client = TestClient(create_app(FraudDetectionEngine()))
    response = client.post(
        "/v1/score",
        json={
            "transaction": {
                "transaction_amount": 40,
                "customer_id": "cust-1",
                "merchant": "shop-7",
                "currency_code": "BRL",
                "type": "pix",
                "date": "2024-03-02 11:00",
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["label_types"] == []
    assert body["decision"] != "HIGH_RISK"
    assert body["graph_status"] == "insufficient_history"


def test_no_history_does_not_invent_a_graph_score():
    engine = FraudDetectionEngine()
    result = engine.score(
        Transaction(
            transaction_id="solo",
            timestamp="2024-06-01T12:00:00",
            amount=18000,
            currency="EUR",
            transaction_type="transfer",
            sender_id="alpha",
            receiver_id="beta",
            country_from="FR",
            country_to="DE",
        ),
        [],
    )
    assert result.graph_status == "insufficient_history"
    assert result.model_scores.graph == 0
    assert "CARD_FRAUD" not in result.label_types
    assert result.decision != Decision.HIGH_RISK


def test_possible_sanctions_match_is_not_a_confirmed_floor():
    index = SanctionsIndex([SanctionsEntry(name="NORTH WIND TRADING", list_name="OFAC_SDN")])
    engine = FraudDetectionEngine(sanctions=index)
    result = engine.score(
        Transaction(
            transaction_id="maybe",
            timestamp="2024-06-01T12:00:00",
            amount=100,
            sender_id="a",
            receiver_id="b",
            receiver_name="NORTH WIND TRADE",
        ),
        [],
    )
    assert index.match_scored("NORTH WIND TRADE") is None
    possible = index.match_scored("NORTH WIND TRADE", possible=True)
    assert possible is not None and possible[1] < 0.92
    assert result.external_checks.sanctions is False
    assert result.external_checks.sanctions_status == "possible_match"
    assert result.risk_score < 75


def test_repeated_legitimate_payment_is_not_high_risk():
    engine = FraudDetectionEngine()
    current = Transaction(
        transaction_id="rep-2",
        timestamp="2024-06-03T11:00:00",
        amount=420,
        currency="TND",
        sender_id="shop",
        receiver_id="supplier",
        country_from="TN",
        country_to="TN",
    )
    prior = current.model_copy(
        update={"transaction_id": "rep-1", "timestamp": datetime(2024, 6, 2, 11, 0)}
    )
    result = engine.score(current, [prior])
    assert result.decision != Decision.HIGH_RISK
    assert "duplicate_invoice" not in result.fraud_types


@pytest.mark.skipif(
    not (ARTIFACTS / "supervised.joblib").exists(),
    reason="trained artifacts are produced by python -m fraud_detection train",
)
def test_real_model_does_not_call_card_fraud_on_unseen_transfers():
    from fraud_detection.models.general_behavior import GeneralBehavior
    from fraud_detection.models.population_anomaly import PopulationAnomaly
    from fraud_detection.models.ulb_specialist import ULBCardSpecialist

    anomaly_path = ARTIFACTS / "anomaly.joblib"
    general_path = ARTIFACTS / "general_behavior.joblib"
    ulb_path = ARTIFACTS / "ulb_card.joblib"
    engine = FraudDetectionEngine(
        supervised=SupervisedDetector.load(ARTIFACTS / "supervised.joblib"),
        population_anomaly=PopulationAnomaly.load(anomaly_path) if anomaly_path.exists() else None,
        general_behavior=GeneralBehavior.load(general_path) if general_path.exists() else None,
        ulb_specialist=ULBCardSpecialist.load(ulb_path) if ulb_path.exists() else None,
    )
    plain = engine.score(
        Transaction(
            transaction_id="unseen-wire",
            timestamp="2024-11-04T14:10:00",
            amount=250000,
            currency="USD",
            transaction_type="transfer",
            sender_id="real-sender-88",
            receiver_id="real-receiver-17",
            country_from="FR",
            country_to="DE",
        ),
        [],
    )
    assert "CARD_FRAUD" not in plain.model_scores.supervised_by_type
    assert "ACCOUNT_TAKEOVER" not in plain.model_scores.supervised_by_type
    assert plain.decision != Decision.HIGH_RISK
    assert plain.graph_status == "insufficient_history"
    assert plain.model_scores.supervised is None or plain.model_scores.supervised < 0.5

    card = engine.score(
        Transaction(
            transaction_id="unseen-card",
            timestamp="2024-11-04T16:00:00",
            amount=85,
            currency="EUR",
            transaction_type="card",
            channel="card",
            sender_id="card-holder",
            receiver_id="merchant-12",
        ),
        [],
    )
    assert "ACCOUNT_TAKEOVER" not in card.model_scores.supervised_by_type
    assert "AML_LAUNDERING" not in card.model_scores.supervised_by_type
    assert set(card.model_scores.supervised_by_type) <= {"CARD_FRAUD"}
    assert card.decision != Decision.HIGH_RISK

    drain = engine.score(
        Transaction(
            transaction_id="unseen-drain",
            timestamp="2024-11-04T09:00:00",
            amount=6400,
            currency="USD",
            transaction_type="cash_out",
            sender_id="wallet-1",
            receiver_id="wallet-2",
            old_balance=6400,
            new_balance=0,
        ),
        [],
    )
    assert "CARD_FRAUD" not in drain.model_scores.supervised_by_type
    assert "ACCOUNT_TAKEOVER" in drain.model_scores.supervised_by_type

    history = []
    start = datetime(2024, 10, 1, 10, 0)
    for index in range(6):
        history.append(
            Transaction(
                transaction_id=f"hist-{index}",
                timestamp=start + timedelta(days=index),
                amount=400 + index,
                currency="EUR",
                transaction_type="transfer",
                sender_id="payroll-co",
                receiver_id="landlord",
                country_from="FR",
                country_to="FR",
            )
        )
    repeated = engine.score(
        history[-1].model_copy(
            update={"transaction_id": "hist-next", "timestamp": start + timedelta(days=8), "amount": 410}
        ),
        history,
    )
    assert repeated.decision != Decision.HIGH_RISK
    assert "CARD_FRAUD" not in repeated.label_types
