from __future__ import annotations

from fraud_detection.data.adapters.common import Row, canonical_currency, flag, parse_timestamp, public_metadata, text
from fraud_detection.schema import LabelType, Transaction


def adapt_saml_d(row: Row) -> Transaction:
    fraud = flag(row.get("Is_laundering", row.get("Is Laundering", 0)))
    sender = str(row.get("Sender_account") or row["sender_account"])
    receiver = str(row.get("Receiver_account") or row["receiver_account"])
    raw_time = row.get("Date") or row.get("Time") or row["timestamp"]
    timestamp = parse_timestamp(raw_time)
    laundering_type = row.get("Laundering_type") or row.get("Laundering type")
    return Transaction(
        transaction_id=f"saml-{sender}-{receiver}-{timestamp.isoformat()}",
        timestamp=timestamp,
        amount=float(row["Amount"] if "Amount" in row else row["amount"]),
        currency=canonical_currency(row.get("Payment_currency") or row.get("Payment currency") or "USD"),
        transaction_type=str(row.get("Payment_type") or row.get("Payment type") or "transfer").lower(),
        sender_id=sender,
        receiver_id=receiver,
        country_from=text(row.get("Sender_bank_location") or row.get("Sender bank location")),
        country_to=text(row.get("Receiver_bank_location") or row.get("Receiver bank location")),
        dataset="saml_d",
        label_type=LabelType.AML_LAUNDERING if fraud else None,
        metadata=public_metadata(
            "synthetic_simulated",
            laundering_type=None if laundering_type is None else str(laundering_type),
        ),
    )
