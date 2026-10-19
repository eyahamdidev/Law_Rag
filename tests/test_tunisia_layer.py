from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from fraud_detection.api.app import create_app
from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.schema import Decision, EntityRecord, SanctionsEntry, Transaction
from fraud_detection.tunisia.country import detection_reasons


def _tx(**kwargs) -> Transaction:
    payload = {
        "transaction_id": "tn-1",
        "timestamp": "2025-06-12T11:00:00",
        "amount": 80,
        "currency": "TND",
        "sender_id": "buyer",
        "receiver_id": "merchant",
        "country_from": "TN",
        "country_to": "TN",
    }
    payload.update(kwargs)
    return Transaction(**payload)


def test_dataset_name_does_not_make_a_payment_tunisian():
    transaction = _tx(
        currency="EUR",
        country_from="FR",
        country_to="FR",
        dataset="tunisia_synth",
    )
    assert detection_reasons(transaction) == []
    result = FraudDetectionEngine().score(transaction, [])
    assert result.tunisia.coverage == "NOT_APPLICABLE"
    assert result.tunisia.tunisia_score is None
    assert result.tunisia.country is None


def test_tnd_card_payment_uses_context_and_no_tunisia_model():
    result = FraudDetectionEngine().score(
        _tx(transaction_id="card-1", amount=90, channel="card", transaction_type="card"),
        [],
    )
    tunisia = result.tunisia
    assert tunisia.country == "TN"
    assert tunisia.coverage == "MEDIUM"
    assert tunisia.tunisia_score is None
    assert tunisia.model_trained is False
    assert tunisia.specialist is None
    assert tunisia.global_score is None
    assert "bct_payment_statistics_aggregate" in tunisia.data_sources_used
    assert tunisia.context["payment_market"]["published_channel"] == "Cartes bancaires"
    assert tunisia.context["payment_market"]["level"] == "AGGREGATE"
    assert result.decision != Decision.HIGH_RISK


def test_tunisian_transfer_is_not_high_risk_by_country():
    result = FraudDetectionEngine().score(
        _tx(transaction_id="wire-1", amount=900, transaction_type="transfer", channel="virement"),
        [],
    )
    assert result.tunisia.country == "TN"
    assert result.tunisia.tunisia_score is None
    assert result.decision != Decision.HIGH_RISK
    assert "ctaf_cross_border_pass_through" not in result.fraud_types


def test_cash_withdrawal_has_no_fabricated_atm_baseline():
    result = FraudDetectionEngine().score(
        _tx(
            transaction_id="atm-1",
            amount=200,
            channel="atm",
            transaction_type="cash_withdrawal",
        ),
        [],
    )
    assert result.tunisia.tunisia_score is None
    assert "payment_market" not in result.tunisia.context
    assert result.decision != Decision.HIGH_RISK


def test_cross_border_country_alone_is_not_a_tunisia_fraud_score():
    result = FraudDetectionEngine().score(
        _tx(
            transaction_id="xb-1",
            amount=1500,
            transaction_type="transfer",
            country_from="TN",
            country_to="FR",
        ),
        [],
    )
    assert "country_to:TN" not in result.tunisia.country_detection
    assert "country_from:TN" in result.tunisia.country_detection
    assert result.tunisia.tunisia_score is None
    assert "cross_border_flow" not in result.fraud_types
    assert result.decision != Decision.HIGH_RISK


def test_missing_tunisia_fields_keep_a_null_tunisia_score():
    client = TestClient(create_app(FraudDetectionEngine()))
    response = client.post(
        "/v1/score",
        json={"transaction": {"amount": 40, "currency": "TND"}},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["data_coverage"] == "LOW"
    assert body["tunisia"]["country"] == "TN"
    assert body["tunisia"]["tunisia_score"] is None
    assert body["tunisia"]["coverage"] in {"LOW", "MEDIUM"}
    assert body["tunisia"]["model_status"] == "not_trained_no_transaction_labels"


def test_new_beneficiary_does_not_invent_a_tunisia_probability():
    engine = FraudDetectionEngine()
    current = _tx(
        transaction_id="new-b",
        amount=8000,
        timestamp="2025-06-20T11:00:00",
        receiver_id="new-shop",
    )
    prior = _tx(
        transaction_id="old-b",
        amount=400,
        timestamp="2025-06-01T11:00:00",
        receiver_id="usual-shop",
    )
    result = engine.score(current, [prior])
    assert "new_counterparty" in result.fraud_types
    assert result.tunisia.tunisia_score is None
    assert result.tunisia.specialist is None


def test_high_value_domestic_transfer_is_not_automatically_fraud():
    result = FraudDetectionEngine().score(
        _tx(transaction_id="big-1", amount=100000, transaction_type="transfer"),
        [],
    )
    assert result.tunisia.tunisia_score is None
    assert result.decision != Decision.HIGH_RISK


def test_repeated_international_money_orders_cite_the_ctaf_case():
    engine = FraudDetectionEngine()
    receiver = "collector"
    history = []
    start = datetime(2025, 3, 1, 10, 0)
    for index in range(7):
        history.append(
            _tx(
                transaction_id=f"mo-{index}",
                timestamp=start + timedelta(days=index * 3),
                amount=500 + index,
                sender_id=f"sender-{index}",
                receiver_id=receiver,
                transaction_type="money_order",
                channel="western_union",
                country_from="FR",
                country_to="TN",
            )
        )
    current = _tx(
        transaction_id="mo-7",
        timestamp=start + timedelta(days=30),
        amount=700,
        sender_id="sender-7",
        receiver_id=receiver,
        transaction_type="money_order",
        channel="western_union",
        country_from="IT",
        country_to="TN",
    )
    result = engine.score(current, history)
    assert "ctaf_repeated_international_money_orders" in result.fraud_types
    assert result.tunisia.context["ctaf_pattern_ids"] == ["CTAF-2024-T7"]
    assert result.tunisia.tunisia_score is None
    assert result.decision == Decision.HIGH_RISK


def test_legitimate_tunisian_merchant_stays_low_risk():
    merchant = EntityRecord(
        entity_id="merchant",
        name="Epicerie Medina",
        kind="company",
        country="TN",
        governorate="Tunis",
        activity="retail",
        registered_on=datetime(2016, 4, 1),
        status="active",
    )
    result = FraudDetectionEngine().score(
        _tx(transaction_id="legit-1", amount=45, channel="card", transaction_type="card"),
        [],
        [merchant],
    )
    assert result.decision != Decision.HIGH_RISK
    assert result.tunisia.tunisia_score is None
    assert "ctaf_activity_mismatch_cash_cross_border" not in result.fraud_types


def test_sanctions_hit_on_a_tunisian_payment_keeps_tunisia_score_null():
    index = SanctionsIndex([SanctionsEntry(name="AEROCARIBBEAN AIRLINES", list_name="OFAC")])
    engine = FraudDetectionEngine(sanctions=index)
    result = engine.score(
        _tx(
            transaction_id="sanc-1",
            amount=1200,
            receiver_name="AEROCARIBBEAN AIRLINES",
            transaction_type="transfer",
        ),
        [],
    )
    assert result.external_checks.sanctions is True
    assert result.tunisia.sanctions_score == 1.0
    assert result.tunisia.tunisia_score is None
    assert result.risk_score >= 75
    assert "CARD_FRAUD" not in result.label_types
