from __future__ import annotations

from fraud_detection.data.adapters.common import Row, flag, parse_timestamp, public_metadata
from fraud_detection.schema import LabelType, Transaction


def adapt_handbook(row: Row) -> Transaction:
    fraud = flag(row["TX_FRAUD"])
    return Transaction(
        transaction_id=f"handbook-{row['CUSTOMER_ID']}-{row['TX_DATETIME']}",
        timestamp=parse_timestamp(row["TX_DATETIME"]),
        amount=float(row["TX_AMOUNT"]),
        currency="EUR",
        transaction_type="card",
        channel="card",
        sender_id=str(row["CUSTOMER_ID"]),
        receiver_id=str(row["TERMINAL_ID"]),
        dataset="fraud_handbook",
        label_type=LabelType.CARD_FRAUD if fraud else None,
        metadata=public_metadata("synthetic_simulated"),
    )
