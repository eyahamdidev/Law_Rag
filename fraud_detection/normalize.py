from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

TN_ZONE = ZoneInfo("Africa/Tunis")

_COUNTRY_ALIASES = {
    "TUNISIA": "TN",
    "TUN": "TN",
    "FRANCE": "FR",
    "ITALY": "IT",
    "GERMANY": "DE",
    "DEU": "DE",
    "ALGERIA": "DZ",
    "LIBYA": "LY",
    "LBY": "LY",
    "USA": "US",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "UK": "GB",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "ENGLAND": "GB",
}

_LEGAL_SUFFIXES = {
    "SARL",
    "SA",
    "SUARL",
    "LTD",
    "LIMITED",
    "LLC",
    "INC",
    "INCORPORATED",
    "GMBH",
    "PLC",
    "CO",
    "COMPANY",
    "CORP",
    "CORPORATION",
    "BV",
    "NV",
    "AG",
}


def country_code(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.strip().upper().split())
    if not text:
        return None
    return _COUNTRY_ALIASES.get(text, text)


def local_hour(timestamp: datetime) -> int:
    """Hour in Africa/Tunis. Naive timestamps are already civil Tunis time."""
    if timestamp.tzinfo is None:
        return timestamp.hour
    return timestamp.astimezone(TN_ZONE).hour


def civil_date(timestamp: datetime):
    if timestamp.tzinfo is None:
        return timestamp.date()
    return timestamp.astimezone(TN_ZONE).date()


def normalize_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    letters = re.sub(r"[^A-Za-z0-9]+", " ", without_marks).upper()
    return re.sub(r"\s+", " ", letters).strip()


def strip_legal_suffix(normalized_name: str) -> str:
    tokens = [token for token in normalized_name.split() if token not in _LEGAL_SUFFIXES]
    return " ".join(tokens).strip()


_FIELD_ALIASES = {
    "transaction_amount": "amount",
    "amt": "amount",
    "sender": "sender_id",
    "source_account": "sender_id",
    "sender_account": "sender_id",
    "from_account": "sender_id",
    "customer": "sender_id",
    "customer_id": "sender_id",
    "receiver": "receiver_id",
    "beneficiary": "receiver_id",
    "beneficiary_id": "receiver_id",
    "destination_account": "receiver_id",
    "to_account": "receiver_id",
    "merchant_id": "receiver_id",
    "transaction_time": "timestamp",
    "datetime": "timestamp",
    "txn_date": "timestamp",
    "country": "country_from",
    "country_code": "country_from",
    "currency_code": "currency",
    "txn_type": "transaction_type",
    "payment_type": "transaction_type",
    "transaction_type_name": "transaction_type",
}


def normalize_transaction_payload(payload: dict) -> dict:
    """Map common field aliases onto the canonical transaction.

    Missing core fields stay explicit in metadata. They are not filled with a
    real customer's identity or a real clock.
    """
    from fraud_detection.data.adapters.common import canonical_currency, parse_timestamp

    data = dict(payload)
    metadata = dict(data.get("metadata") or {})
    for source, target in _FIELD_ALIASES.items():
        if source in data and data.get(target) in (None, ""):
            data[target] = data[source]
    if data.get("receiver_id") in (None, "") and data.get("merchant") not in (None, ""):
        data["receiver_id"] = data["merchant"]
    if data.get("timestamp") in (None, "") and data.get("date") not in (None, ""):
        data["timestamp"] = data["date"]
    if data.get("transaction_type") in (None, "") and data.get("type") not in (None, ""):
        data["transaction_type"] = data["type"]

    pca = dict(metadata.get("pca") or {})
    for index in range(1, 29):
        key = f"V{index}"
        if key in data and data[key] not in (None, ""):
            pca[key] = data[key]
    if pca:
        metadata["pca"] = pca

    amount = data.get("amount")
    if isinstance(amount, str):
        cleaned = amount.replace(",", "").replace(" ", "").strip()
        data["amount"] = float(cleaned) if cleaned else 0.0
    if data.get("amount") in (None, ""):
        data["amount"] = 0.0
        metadata["missing_amount"] = True

    if data.get("timestamp") in (None, ""):
        data["timestamp"] = "1970-01-01T12:00:00"
        metadata["missing_timestamp"] = True
    else:
        try:
            data["timestamp"] = parse_timestamp(data["timestamp"])
        except (TypeError, ValueError):
            text = str(data["timestamp"]).strip().replace("Z", "+00:00")
            try:
                data["timestamp"] = datetime.fromisoformat(text)
            except ValueError:
                data["timestamp"] = "1970-01-01T12:00:00"
                metadata["missing_timestamp"] = True

    if not data.get("sender_id"):
        data["sender_id"] = "missing-sender"
        metadata["missing_sender"] = True
    if not data.get("receiver_id"):
        data["receiver_id"] = "missing-receiver"
        metadata["missing_receiver"] = True
    if not data.get("transaction_id"):
        import hashlib

        raw = repr(sorted((str(key), str(value)) for key, value in payload.items())).encode()
        data["transaction_id"] = "missing-id-" + hashlib.sha256(raw).hexdigest()[:12]

    currency = data.get("currency")
    if currency in (None, ""):
        data["currency"] = "UNK"
        metadata["missing_currency"] = True
    else:
        canonical = canonical_currency(currency)
        data["currency"] = canonical
        if canonical == "UNK" or len(canonical) != 3:
            metadata["unknown_currency"] = True

    data["sender_id"] = str(data["sender_id"])
    data["receiver_id"] = str(data["receiver_id"])
    data["transaction_id"] = str(data["transaction_id"])
    if data.get("transaction_type") not in (None, ""):
        data["transaction_type"] = str(data["transaction_type"]).strip().lower()
    metadata["data_coverage_inputs"] = True
    data["metadata"] = metadata
    return data
