from __future__ import annotations

from fraud_detection.normalize import country_code
from fraud_detection.schema import Transaction


def detection_reasons(transaction: Transaction) -> list[str]:
    """Why a payment is treated as Tunisia-related.

    Currency and country fields are the only routing signals. The dataset name
    is ignored on purpose: a row labeled tunisia_synth is not Tunisian evidence.
    """
    reasons: list[str] = []
    currency = (transaction.currency or "").strip().upper()
    if currency == "TND":
        reasons.append("currency:TND")
    source = country_code(transaction.country_from)
    destination = country_code(transaction.country_to)
    if source == "TN":
        reasons.append("country_from:TN")
    if destination == "TN":
        reasons.append("country_to:TN")
    return reasons


def is_tunisian(transaction: Transaction) -> bool:
    return bool(detection_reasons(transaction))
