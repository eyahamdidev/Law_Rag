from __future__ import annotations

from datetime import datetime
from typing import Any

from fraud_detection.schema import LabelType, Transaction

Row = dict[str, Any]

_CURRENCY = {
    "us dollar": "USD",
    "usd": "USD",
    "euro": "EUR",
    "eur": "EUR",
    "uk pound": "GBP",
    "british pound": "GBP",
    "pound sterling": "GBP",
    "yuan": "CNY",
    "renminbi": "CNY",
    "ruble": "RUB",
    "bitcoin": "BTC",
    "australian dollar": "AUD",
    "canadian dollar": "CAD",
    "swiss franc": "CHF",
    "yen": "JPY",
    "rupee": "INR",
    "shekel": "ILS",
    "mexican peso": "MXN",
    "peso": "MXN",
    "saudi riyal": "SAR",
    "naira": "NGN",
}


def canonical_currency(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    key = " ".join(text.lower().split())
    if key in _CURRENCY:
        return _CURRENCY[key]
    if len(text) == 3 and text.isalpha():
        return text.upper()
    return text.upper() if text else "UNK"


def unquote(value: Any) -> str:
    return str(value).strip().strip("'\"").strip()


def flag(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def as_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        if str(value).lower() == "nan":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised timestamp: {value}")


def public_metadata(source_kind: str, **extra: Any) -> dict[str, Any]:
    """Mark a downloaded public file.

    `data_origin` means the file is a public dataset, not that the rows are a
    real bank ledger. `source_kind` says which of those it is.
    """
    payload: dict[str, Any] = {"data_origin": "REAL_PUBLIC_DATA", "source_kind": source_kind}
    payload.update(extra)
    return payload


def text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = unquote(value)
    if not cleaned or cleaned.lower() == "nan":
        return None
    return cleaned


def stack_datasets(groups: list[list[Transaction]]) -> list[Transaction]:
    stacked: list[Transaction] = []
    for group in groups:
        stacked.extend(group)
    return stacked


def training_pairs(transactions: list[Transaction]) -> list[tuple[Transaction, LabelType | None]]:
    pairs = []
    for transaction in transactions:
        if transaction.metadata.get("unlabeled"):
            continue
        pairs.append((transaction, transaction.label_type))
    return pairs
