from __future__ import annotations

import json
from functools import lru_cache

from fraud_detection.paths import PACKAGE

_BASELINE = PACKAGE / "data" / "processed" / "tunisia" / "tunisia_payment_market_baseline.json"

_CHANNEL_MAP = {
    "card": "Cartes bancaires",
    "credit_card": "Cartes bancaires",
    "debit_card": "Cartes bancaires",
    "pos": "Cartes bancaires",
    "tpe": "Cartes bancaires",
    "foreign_card": "Cartes bancaires",
    "cheque": "Chèques",
    "check": "Chèques",
    "virement": "Virements",
    "transfer": "Virements",
    "wire": "Virements",
    "sepa": "Virements",
    "swift": "Virements",
    "direct_debit": "Prélèvements",
    "prelevement": "Prélèvements",
    "ecommerce": "Paiements électroniques*",
    "e_commerce": "Paiements électroniques*",
    "electronic": "Paiements électroniques*",
    "mobile": "Paiements électroniques*",
    "mobile_payment": "Paiements électroniques*",
}


@lru_cache(maxsize=1)
def payment_baseline() -> tuple[dict, ...]:
    if not _BASELINE.exists():
        return ()
    payload = json.loads(_BASELINE.read_text(encoding="utf-8"))
    return tuple(payload)


def baseline_available() -> bool:
    return bool(payment_baseline())


def channel_key(channel: str | None, transaction_type: str | None) -> str | None:
    for raw in (channel, transaction_type):
        if not raw:
            continue
        key = raw.strip().lower().replace(" ", "_").replace("-", "_")
        if key in _CHANNEL_MAP:
            return _CHANNEL_MAP[key]
    return None


def latest_channel_average(channel: str | None, transaction_type: str | None) -> dict | None:
    """Latest published BCT average for a payment instrument, if both totals exist."""
    published = channel_key(channel, transaction_type)
    if published is None:
        return None
    candidates = [
        row
        for row in payment_baseline()
        if row.get("channel") == published and row.get("average_value") is not None
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda row: row["period"])
    return {
        "published_channel": published,
        "period": latest["period"],
        "average_value_tnd": latest["average_value"],
        "transaction_count": latest["transaction_count"],
        "transaction_value_tnd": latest["transaction_value"],
        "source": latest["source"],
        "level": "AGGREGATE",
    }
