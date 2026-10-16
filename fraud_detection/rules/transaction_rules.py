from __future__ import annotations

import statistics

from fraud_detection.ledger import since
from fraud_detection.normalize import country_code, local_hour
from fraud_detection.rules.context import RuleContext
from fraud_detection.schema import LabelType, Severity, Signal


def _signal(
    name: str,
    severity: Severity,
    labels: list[LabelType],
    detail: str,
    evidence: dict,
) -> Signal:
    return Signal(signal=name, severity=severity, label_types=labels, detail=detail, evidence=evidence)


def duplicate_payment(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    window_start = since(tx.timestamp, hours=48)
    repeats = [
        item
        for item in ctx.ledger.outgoing(tx.sender_id)
        if item.receiver_id == tx.receiver_id
        and item.timestamp >= window_start
        and abs(item.amount - tx.amount) <= max(1.0, 0.01 * tx.amount)
    ]
    same_invoice = [
        item for item in ctx.ledger.prior if tx.invoice_id and item.invoice_id == tx.invoice_id
    ]
    same_expense = [
        item for item in ctx.ledger.prior if tx.expense_id and item.expense_id == tx.expense_id
    ]
    count = len(repeats) + 1
    if tx.invoice_id and (same_invoice or repeats):
        name = "duplicate_invoice"
        label = LabelType.INVOICE_FRAUD
    elif tx.expense_id and (same_expense or repeats):
        name = "duplicate_expense"
        label = LabelType.EXPENSE_FRAUD
    elif count >= 3:
        name = "duplicate_transaction"
        label = LabelType.UNKNOWN
    else:
        return []
    return [
        _signal(
            name,
            Severity.HIGH,
            [label],
            (
                f"The same payment of {tx.amount:.0f} {tx.currency} from {tx.sender_id} "
                f"to {tx.receiver_id} appears {max(count, len(same_invoice) + 1, len(same_expense) + 1)} "
                "times inside 48 hours."
            ),
            {"repeat_count": count},
        )
    ]


def unusual_velocity(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    window_start = since(tx.timestamp, hours=1)
    count = 1 + sum(1 for item in ctx.ledger.outgoing(tx.sender_id) if item.timestamp >= window_start)
    if count < 8:
        return []
    return [
        _signal(
            "unusual_transaction_velocity",
            Severity.HIGH,
            [LabelType.ANOMALY, LabelType.ACCOUNT_TAKEOVER],
            f"{tx.sender_id} sent {count} transactions within one hour.",
            {"count_1h": count},
        )
    ]


def _round_thousand(amount: float) -> bool:
    return amount >= 1000 and abs(amount % 1000) <= 1e-6


def round_number_burst(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    if not _round_thousand(tx.amount):
        return []
    window_start = since(tx.timestamp, hours=24)
    count = 1 + sum(
        1
        for item in ctx.ledger.outgoing(tx.sender_id)
        if item.timestamp >= window_start and _round_thousand(item.amount)
    )
    if count < 4:
        return []
    return [
        _signal(
            "round_number_burst",
            Severity.MEDIUM,
            [LabelType.ANOMALY],
            f"{tx.sender_id} sent {count} round-thousand payments within 24 hours.",
            {"round_count_24h": count},
        )
    ]


def _just_below_threshold(amount: float) -> bool:
    return any(low <= amount < high for low, high in ((9000, 10000), (4900, 5000), (2900, 3000)))


def structuring_just_below(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    if not _just_below_threshold(tx.amount):
        return []
    window_start = since(tx.timestamp, days=7)
    count = 1 + sum(
        1
        for item in ctx.ledger.outgoing(tx.sender_id)
        if item.timestamp >= window_start and _just_below_threshold(item.amount)
    )
    if count < 3:
        return []
    return [
        _signal(
            "structuring_just_below_threshold",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            f"{tx.sender_id} sent {count} amounts just under a round threshold within 7 days.",
            {"structuring_count": count},
        )
    ]


def unusual_night_activity(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    if tx.metadata.get("missing_timestamp"):
        return []
    hour = local_hour(tx.timestamp)
    if not (hour >= 23 or hour <= 5):
        return []
    prior_amounts = [item.amount for item in ctx.ledger.outgoing(tx.sender_id)]
    if len(prior_amounts) >= 5:
        typical = statistics.median(prior_amounts)
        if tx.amount < 3 * typical:
            return []
    elif tx.amount < 10000:
        return []
    return [
        _signal(
            "unusual_night_activity",
            Severity.MEDIUM,
            [LabelType.ANOMALY],
            f"The payment of {tx.amount:.0f} {tx.currency} was made at {hour:02d}:00, outside this sender's usual hours.",
            {"hour": hour},
        )
    ]


def new_counterparty_large(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    prior = ctx.ledger.outgoing(tx.sender_id)
    if not prior:
        return []
    if any(item.receiver_id == tx.receiver_id for item in prior):
        return []
    typical = statistics.median(item.amount for item in prior)
    if tx.amount < max(5000.0, 5 * typical):
        return []
    source = country_code(tx.country_from)
    destination = country_code(tx.country_to)
    # Cross-border means the two countries differ. A domestic payment in any
    # country is not "foreign" merely because it is outside Tunisia.
    foreign = bool(source and destination and source != destination)
    severity = Severity.HIGH if foreign else Severity.MEDIUM
    where = "a new cross-border beneficiary" if foreign else "a beneficiary with no prior payments"
    return [
        _signal(
            "new_counterparty",
            severity,
            [LabelType.ACCOUNT_TAKEOVER],
            f"First payment to {where} is {tx.amount:.0f} {tx.currency}, above this sender's usual size.",
            {"amount": tx.amount, "typical_amount": typical, "foreign": foreign},
        )
    ]


def sudden_geography_change(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    current = country_code(tx.country_from)
    if current is None:
        return []
    recent: list[str] = []
    for item in ctx.ledger.outgoing(tx.sender_id)[-5:]:
        code = country_code(item.country_from)
        if code:
            recent.append(code)
    if len(recent) < 3 or len(set(recent)) != 1 or current in set(recent):
        return []
    return [
        _signal(
            "sudden_geography_change",
            Severity.MEDIUM,
            [LabelType.ACCOUNT_TAKEOVER],
            f"The sender's country changed from {recent[-1]} to {current} after a stable history.",
            {"previous_country": recent[-1], "country": current},
        )
    ]


def impossible_balance(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    if tx.old_balance is None or tx.new_balance is None:
        return []
    tolerance = max(1.0, 0.01 * tx.amount)
    outflow = tx.old_balance - tx.amount
    inflow = tx.old_balance + tx.amount
    if abs(tx.new_balance - outflow) <= tolerance or abs(tx.new_balance - inflow) <= tolerance:
        return []
    return [
        _signal(
            "impossible_balance_movement",
            Severity.HIGH,
            [LabelType.ANOMALY],
            (
                f"The balance moved from {tx.old_balance:.0f} to {tx.new_balance:.0f} "
                f"on a {tx.amount:.0f} {tx.currency} payment, which does not match either direction."
            ),
            {"old_balance": tx.old_balance, "new_balance": tx.new_balance},
        )
    ]

