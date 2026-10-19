from datetime import datetime, timedelta

import numpy as np

from fraud_detection.ledger import Ledger
from fraud_detection.models.feature_stats import RunningMedian, median_of
from fraud_detection.models.features import feature_row
from fraud_detection.models.online_features import OnlineFeatures
from fraud_detection.schema import Transaction


def test_running_median_matches_batch_median():
    values = [4.0, 1.0, 9.0, 2.0, 8.0, 3.0]
    tracker = RunningMedian()
    for index, value in enumerate(values, start=1):
        tracker.add(value)
        assert tracker.median() == median_of(values[:index])


def test_online_features_match_the_ledger_features():
    online = OnlineFeatures()
    history: list[Transaction] = []
    start = datetime(2024, 5, 1, 10, 0)
    specs = [
        ("a1", "A", "B", 100.0, 0, "TND", "TN", "TN", None),
        ("a2", "A", "B", 120.0, 2, "TND", "TN", "TN", None),
        ("a3", "C", "A", 80.0, 3, "EUR", "FR", "TN", None),
        ("a4", "A", "D", 5000.0, 30, "TND", "TN", "FR", "card"),
        ("a5", "A", "B", 120.0, 40, "TND", "TN", "TN", None),
        ("a6", "B", "A", 50.0, 48, "USD", "US", "TN", None),
        ("a7", "A", "E", 990.0, 80, "TND", "TN", "LY", None),
    ]
    for tx_id, sender, receiver, amount, hours, currency, source, dest, channel in specs:
        transaction = Transaction(
            transaction_id=tx_id,
            timestamp=start + timedelta(hours=hours),
            amount=amount,
            currency=currency,
            sender_id=sender,
            receiver_id=receiver,
            country_from=source,
            country_to=dest,
            channel=channel,
            old_balance=1000,
            new_balance=1000 - amount,
        )
        expected = feature_row(Ledger(transaction, history))
        produced = online.transform_transaction(transaction)
        assert np.allclose(produced, expected, rtol=1e-6, atol=1e-6), list(zip(expected, produced))
        history.append(transaction)
