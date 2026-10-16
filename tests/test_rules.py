from datetime import datetime, timedelta

from fraud_detection.entity_intelligence.registry import EntityRegistry
from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.ledger import Ledger, apply_entity_defaults
from fraud_detection.rules import run_rules
from fraud_detection.rules.context import RuleContext
from fraud_detection.schema import EntityRecord, LabelType, SanctionsEntry, Transaction


def _tx(tx_id: str, hour: int, amount: float, sender: str = "A", receiver: str = "B", **extra) -> Transaction:
    delta = extra.pop("delta", timedelta())
    fields = {
        "transaction_id": tx_id,
        "timestamp": datetime(2024, 5, 1, hour, 0) + delta,
        "amount": amount,
        "sender_id": sender,
        "receiver_id": receiver,
        "currency": "TND",
        "country_from": "TN",
        "country_to": "TN",
    }
    fields.update(extra)
    return Transaction(**fields)


def _signals(current: Transaction, history: list[Transaction], entities: list[EntityRecord] | None = None):
    registry = EntityRegistry(entities or [])
    enriched = apply_entity_defaults(current, registry.by_id)
    context = RuleContext(Ledger(enriched, history), registry.by_id, registry.loaded)
    return {item.signal: item for item in run_rules(context)}


def test_duplicate_invoice_is_its_own_label():
    first = _tx("1", 9, 1000, invoice_id="FAC-1")
    second = _tx("2", 11, 1000, invoice_id="FAC-1")
    found = _signals(second, [first])
    assert found["duplicate_invoice"].label_types == [LabelType.INVOICE_FRAUD]


def test_structuring_needs_a_repeated_pattern():
    history = [
        _tx("1", 9, 9600, delta=timedelta(days=-2)),
        _tx("2", 9, 9700, delta=timedelta(days=-1)),
    ]
    found = _signals(_tx("3", 9, 9500), history)
    assert "structuring_just_below_threshold" in found
    assert found["structuring_just_below_threshold"].label_types == [LabelType.AML_LAUNDERING]


def test_pass_through_uses_many_payers_then_an_outflow():
    incoming = [
        _tx(f"in-{index}", 10, 1000, sender=f"P{index}", receiver="CO", delta=timedelta(minutes=index))
        for index in range(6)
    ]
    outflow = _tx("out", 12, 5500, sender="CO", receiver="FR", country_to="FR")
    company = EntityRecord(
        entity_id="CO",
        name="Nouvelle",
        registered_on=datetime(2024, 4, 1),
        declared_annual_revenue=100_000,
        country="TN",
    )
    foreign = EntityRecord(entity_id="FR", name="Etranger", kind="account", country="FR")
    found = _signals(outflow, incoming, [company, foreign])
    assert "pass_through_account" in found
    assert "rapid_in_outflow" in found
    assert LabelType.AML_LAUNDERING in found["pass_through_account"].label_types


def test_known_weekly_supplier_is_not_a_new_counterparty():
    history = [_tx(f"h-{index}", 10, 2000, delta=timedelta(weeks=-index)) for index in range(1, 6)]
    found = _signals(_tx("now", 10, 2100), history)
    assert "new_counterparty" not in found
    assert "duplicate_transaction" not in found


def test_sanctions_match_does_not_invent_a_laundering_label():
    current = _tx("s", 10, 500, receiver="BAD", receiver_name="Bad Actor")
    index = SanctionsIndex([SanctionsEntry(name="Bad Actor SARL", list_name="OFAC")])
    engine = FraudDetectionEngine(sanctions=index)
    result = engine.score(current, [])
    assert result.external_checks.sanctions is True
    assert result.decision.value == "HIGH_RISK"
    assert "AML_LAUNDERING" not in result.label_types
    assert "sanctions_match" in result.fraud_types
