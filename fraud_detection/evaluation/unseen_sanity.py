"""Score a fixed set of payments that are not training rows.

Run from the repo root:

    .venv/bin/python -m fraud_detection.evaluation.unseen_sanity

The cases are local fixtures. They are not written into any training file.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta

from fraud_detection.api.app import engine_from_env
from fraud_detection.normalize import normalize_transaction_payload
from fraud_detection.paths import EVAL
from fraud_detection.schema import Transaction

_START = datetime(2024, 11, 18, 11, 0)


def _tx(**fields) -> Transaction:
    base = {
        "transaction_id": "tx",
        "timestamp": _START,
        "amount": 120.0,
        "currency": "EUR",
        "transaction_type": "transfer",
        "sender_id": "fr-sender",
        "receiver_id": "usual-shop",
        "country_from": "FR",
        "country_to": "FR",
    }
    base.update(fields)
    return Transaction(**base)


def _weeks(receiver: str = "usual-shop", amount: float = 120.0, count: int = 6) -> list[Transaction]:
    return [
        _tx(
            transaction_id=f"week-{index}",
            timestamp=_START - timedelta(weeks=count - index),
            amount=amount,
            receiver_id=receiver,
        )
        for index in range(count)
    ]


def _cases() -> list[tuple[str, Transaction, list[Transaction]]]:
    weekly = _weeks()
    rapid_history = [
        _tx(
            transaction_id=f"in-{index}",
            timestamp=_START - timedelta(minutes=40 - index * 8),
            amount=2000,
            sender_id=f"payer-{index}",
            receiver_id="collector",
            country_from="TN",
            country_to="TN",
            currency="TND",
        )
        for index in range(3)
    ]
    velocity = [
        _tx(
            transaction_id=f"fast-{index}",
            timestamp=_START - timedelta(minutes=50 - index * 5),
            amount=80,
            receiver_id=f"dest-{index}",
        )
        for index in range(8)
    ]
    fan_in = [
        _tx(
            transaction_id=f"fanin-{index}",
            timestamp=_START - timedelta(minutes=index * 10),
            amount=500,
            sender_id=f"payer-{index}",
            receiver_id="hub",
            currency="USD",
            country_from="US",
            country_to="US",
        )
        for index in range(10)
    ]
    fan_out = [
        _tx(
            transaction_id=f"fanout-{index}",
            timestamp=_START - timedelta(minutes=20 + index * 25),
            amount=400,
            sender_id="distributor",
            receiver_id=f"payee-{index}",
            currency="USD",
            country_from="US",
            country_to="US",
        )
        for index in range(10)
    ]
    cycle = [
        _tx(
            transaction_id="cycle-ab",
            timestamp=_START - timedelta(hours=2),
            amount=1000,
            sender_id="cycle-a",
            receiver_id="cycle-b",
            currency="EUR",
            country_from="DE",
            country_to="DE",
        ),
        _tx(
            transaction_id="cycle-bc",
            timestamp=_START - timedelta(hours=1),
            amount=1000,
            sender_id="cycle-b",
            receiver_id="cycle-c",
            currency="EUR",
            country_from="DE",
            country_to="DE",
        ),
    ]
    return [
        ("normal_recurring_payment", _tx(transaction_id="recurring", amount=125), weekly),
        ("large_known_beneficiary", _tx(transaction_id="large-known", amount=8000), weekly),
        (
            "repeated_invoice",
            _tx(
                transaction_id="inv-2",
                amount=4200,
                invoice_id="FAC-9",
                receiver_id="supplier",
                timestamp=_START,
            ),
            [
                _tx(
                    transaction_id="inv-1",
                    amount=4200,
                    invoice_id="FAC-9",
                    receiver_id="supplier",
                    timestamp=_START - timedelta(hours=5),
                )
            ],
        ),
        (
            "new_beneficiary_domestic",
            _tx(transaction_id="new-fr", amount=9000, receiver_id="new-shop"),
            weekly,
        ),
        (
            "rapid_incoming_outgoing",
            _tx(
                transaction_id="out-fast",
                timestamp=_START,
                amount=5500,
                sender_id="collector",
                receiver_id="exit",
                currency="TND",
                country_from="TN",
                country_to="LY",
            ),
            rapid_history,
        ),
        (
            "high_velocity",
            _tx(transaction_id="fast-now", amount=90, receiver_id="dest-now"),
            velocity,
        ),
        (
            "unusual_hour",
            _tx(transaction_id="night", timestamp=datetime(2024, 11, 18, 2, 15), amount=400),
            weekly,
        ),
        (
            "many_to_one",
            _tx(
                transaction_id="fanin-now",
                amount=500,
                sender_id="payer-10",
                receiver_id="hub",
                currency="USD",
                country_from="US",
                country_to="US",
            ),
            fan_in,
        ),
        (
            "one_to_many",
            _tx(
                transaction_id="fanout-now",
                amount=400,
                sender_id="distributor",
                receiver_id="payee-10",
                currency="USD",
                country_from="US",
                country_to="US",
            ),
            fan_out,
        ),
        (
            "short_cycle",
            _tx(
                transaction_id="cycle-ca",
                amount=1000,
                sender_id="cycle-c",
                receiver_id="cycle-a",
                currency="EUR",
                country_from="DE",
                country_to="DE",
            ),
            cycle,
        ),
        (
            "cross_border",
            _tx(
                transaction_id="xborder",
                amount=25000,
                currency="TND",
                sender_id="tn-co",
                receiver_id="fr-co",
                country_from="TN",
                country_to="FR",
            ),
            [],
        ),
        ("missing_history", _tx(transaction_id="solo", amount=300), []),
        (
            "incomplete_fields",
            Transaction.model_validate(normalize_transaction_payload({"amount": 50, "currency": "DINARS"})),
            [],
        ),
        (
            "unknown_category_currency",
            _tx(
                transaction_id="pix",
                transaction_type="pix",
                currency="XYZ",
                merchant_category="not-a-real-mcc",
                amount=40,
            ),
            [],
        ),
        (
            "sanctions_hit",
            _tx(
                transaction_id="sanctioned",
                amount=100,
                receiver_name="AEROCARIBBEAN AIRLINES",
                receiver_id="aero",
            ),
            weekly,
        ),
        (
            "ordinary_entity",
            _tx(
                transaction_id="clean-name",
                amount=180,
                sender_name="Epicerie Medina",
                receiver_name="Fournisseur Central",
            ),
            weekly,
        ),
        (
            "unfamiliar_shape",
            _tx(
                transaction_id="gift",
                transaction_type="gift_card_barter",
                channel="qr_kiosk",
                currency="JPY",
                amount=40,
                merchant_category="barter",
            ),
            [],
        ),
    ]


def _finite(value) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    return True


def _record(name: str, result) -> dict:
    scores = result.model_scores
    checks = result.external_checks
    return {
        "case": name,
        "risk_score": result.risk_score,
        "risk_level": result.risk_level,
        "fraud_labels": result.label_types,
        "fraud_types": result.fraud_types,
        "model_scores": {
            "supervised": scores.supervised,
            "supervised_by_type": scores.supervised_by_type,
            "anomaly": scores.anomaly,
            "anomaly_source": scores.anomaly_source,
            "graph": scores.graph,
            "general_behavior": scores.general_behavior,
        },
        "graph_status": result.graph_status,
        "sanctions": {
            "status": checks.sanctions_status,
            "match": checks.sanctions,
            "matched_entity": checks.matched_entity,
            "match_score": checks.match_score,
        },
        "confidence": result.confidence,
        "model_confidence": result.model_confidence,
        "data_coverage": result.data_coverage,
        "requires_human_review": result.requires_human_review,
        "tunisia_score": result.tunisia.tunisia_score,
        "explanation": result.explanation,
    }


def main() -> None:
    started = time.perf_counter()
    engine = engine_from_env()
    load_seconds = time.perf_counter() - started
    rows = []
    timings = []
    for name, current, history in _cases():
        tick = time.perf_counter()
        result = engine.score(current, history)
        timings.append(time.perf_counter() - tick)
        again = engine.score(current, history)
        if result.model_dump() != again.model_dump():
            raise SystemExit(f"{name} is not reproducible")
        row = _record(name, result)
        if not _finite(row):
            raise SystemExit(f"{name} produced a non-finite value")
        rows.append(row)
    payload = {
        "note": "Local fixtures. Not training rows and not test-set metrics.",
        "load_seconds": round(load_seconds, 3),
        "first_score_seconds": round(timings[0], 4),
        "later_score_seconds_median": round(sorted(timings[1:])[len(timings[1:]) // 2], 4),
        "cases": rows,
    }
    destination = EVAL / "unseen_sanity.json"
    destination.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {destination}")
    print(f"load_seconds={payload['load_seconds']} first={payload['first_score_seconds']} later_median={payload['later_score_seconds_median']}")
    for row in rows:
        print(
            f"{row['case']}: risk={row['risk_score']} {row['risk_level']} "
            f"labels={row['fraud_labels']} coverage={row['data_coverage']} "
            f"graph={row['graph_status']}:{row['model_scores']['graph']} "
            f"sanctions={row['sanctions']['status']}"
        )


if __name__ == "__main__":
    main()
