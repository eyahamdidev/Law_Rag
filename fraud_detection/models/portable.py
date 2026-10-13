"""Features that can be computed for a generic payment, and those that cannot.

Simulator-only columns stay in the saved specialist matrices so those models
still load. They are excluded from the general behavioral model and from the
coverage check. Dataset identity is not a feature.
"""

from __future__ import annotations

from fraud_detection.models.features import FEATURE_NAMES
from fraud_detection.schema import Transaction

# PaySim's fraud recipe is "this payment emptied the account". Those three
# columns dominate that head and are absent on a normal bank payment.
SIMULATOR_ONLY_FEATURES = (
    "balance_mismatch",
    "amount_to_old_balance",
    "balance_zeroed",
)

# These are schema flags. On the public training mix they identify which file
# a row came from (card file, Tunisia lab currency, procurement columns).
SCHEMA_FINGERPRINT_FEATURES = (
    "is_tnd",
    "bid_count",
    "award_to_estimate_ratio",
    "is_card",
    "has_invoice",
    "has_expense",
)

EXCLUDED_FROM_GENERAL = frozenset(SIMULATOR_ONLY_FEATURES + SCHEMA_FINGERPRINT_FEATURES)

PORTABLE_FEATURES = tuple(name for name in FEATURE_NAMES if name not in EXCLUDED_FROM_GENERAL)


def portable_indices() -> list[int]:
    positions = {name: index for index, name in enumerate(FEATURE_NAMES)}
    return [positions[name] for name in PORTABLE_FEATURES]


def assess_coverage(
    transaction: Transaction,
    portable_values: list[float] | None,
    bounds: list[tuple[float, float]] | None,
) -> tuple[str, int]:
    """Return HIGH, MEDIUM, or LOW, plus how many portable features fall outside training bounds.

    Missing sender, receiver, or timestamp is low coverage. An unknown currency
    or a moderate range deviation is medium. Being inside the training ranges
    with the core fields present is high.
    """
    metadata = transaction.metadata if isinstance(transaction.metadata, dict) else {}
    sender = transaction.sender_id or ""
    receiver = transaction.receiver_id or ""
    missing_party = sender.startswith("missing-") or receiver.startswith("missing-") or not sender or not receiver
    missing_time = bool(metadata.get("missing_timestamp"))
    outside = 0
    if portable_values is not None and bounds:
        for value, (low, high) in zip(portable_values, bounds):
            if value < low or value > high:
                outside += 1
    fraction = outside / len(bounds) if bounds else 0.0
    if missing_party or missing_time or fraction >= 0.25:
        return "LOW", outside
    unknown_currency = bool(metadata.get("unknown_currency") or metadata.get("missing_currency"))
    if fraction >= 0.10 or unknown_currency:
        return "MEDIUM", outside
    return "HIGH", outside
