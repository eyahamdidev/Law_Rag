from __future__ import annotations

from datetime import datetime, timedelta

from fraud_detection.data.adapters.common import Row, flag, public_metadata
from fraud_detection.schema import LabelType, Transaction


def adapt_ulb_creditcard(row: Row, index: int = 0) -> Transaction:
    """ULB credit-card row.

    The public file has no account identifier, so each row stays an isolated
    card payment. PCA columns are kept in metadata and are not mixed into the
    shared behavioral features.
    """
    seconds = float(row["Time"])
    fraud = flag(row["Class"])
    pca = {key: row[key] for key in row if str(key).startswith("V")}
    return Transaction(
        transaction_id=f"ulb-{index}",
        timestamp=datetime(2013, 9, 1) + timedelta(seconds=seconds),
        amount=float(row["Amount"]),
        currency="EUR",
        transaction_type="card",
        channel="card",
        sender_id=f"ulb-row-{index}",
        receiver_id="ulb-merchant",
        dataset="ulb_creditcard",
        label_type=LabelType.CARD_FRAUD if fraud else None,
        metadata=public_metadata("real_anonymized", pca=pca),
    )
