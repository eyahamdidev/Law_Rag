from __future__ import annotations

from fraud_detection.data.adapters.common import (
    Row,
    as_float,
    canonical_currency,
    flag,
    parse_timestamp,
    public_metadata,
)
from fraud_detection.schema import LabelType, Transaction


def adapt_ibm_aml(row: Row) -> Transaction:
    """IBM AML transaction row (HI/LI small, medium, or large)."""
    sender = f"{row['From Bank']}:{row['Account']}"
    receiver_account = row.get("Account.1", row.get("Account2"))
    receiver = f"{row['To Bank']}:{receiver_account}"
    paid = as_float(row.get("Amount Paid"))
    received = as_float(row.get("Amount Received"))
    amount = paid if paid is not None else received
    if amount is None:
        raise ValueError("IBM AML row has no amount")
    payment_format = str(row.get("Payment Format", "transfer"))
    fraud = flag(row.get("Is Laundering", 0))
    return Transaction(
        transaction_id=f"ibm-{sender}-{receiver}-{row['Timestamp']}-{amount}",
        timestamp=parse_timestamp(row["Timestamp"]),
        amount=amount,
        currency=canonical_currency(row.get("Payment Currency") or row.get("Receiving Currency") or "USD"),
        transaction_type=payment_format.lower(),
        channel="card" if "card" in payment_format.lower() else None,
        sender_id=sender,
        receiver_id=receiver,
        dataset="ibm_aml",
        label_type=LabelType.AML_LAUNDERING if fraud else None,
        metadata=public_metadata("synthetic_simulated"),
    )
