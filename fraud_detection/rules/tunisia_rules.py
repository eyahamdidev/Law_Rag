from __future__ import annotations

from fraud_detection.ledger import since
from fraud_detection.normalize import civil_date, country_code
from fraud_detection.rules.context import RuleContext
from fraud_detection.rules.transaction_rules import _signal
from fraud_detection.schema import LabelType, Severity, Signal


def pass_through_account(ctx: RuleContext) -> list[Signal]:
    """CTAF-style pass-through: many payers in, most of the money straight back out."""
    tx = ctx.tx
    window_start = since(tx.timestamp, hours=6)
    incoming = [item for item in ctx.ledger.incoming(tx.sender_id) if item.timestamp >= window_start]
    payers = {item.sender_id for item in incoming}
    if len(payers) < 5:
        return []
    inflow = sum(item.amount for item in incoming)
    if inflow <= 0 or tx.amount / inflow < 0.70 or tx.receiver_id in payers:
        return []
    foreign = country_code(tx.country_to) not in (None, "TN")
    destination = "a foreign beneficiary" if foreign else "a different beneficiary"
    return [
        _signal(
            "pass_through_account",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                f"The account received funds from {len(payers)} counterparties within 6 hours "
                f"and transferred {tx.amount / inflow:.0%} of that amount to {destination}."
            ),
            {
                "distinct_payers": len(payers),
                "outflow_ratio": round(tx.amount / inflow, 3),
                "foreign": foreign,
            },
        )
    ]


def _company_age_days(ctx: RuleContext, entity_id: str) -> int | None:
    if entity_id == ctx.tx.sender_id and ctx.tx.company_age_days is not None:
        return ctx.tx.company_age_days
    entity = ctx.entity(entity_id)
    if entity is None or entity.registered_on is None:
        return None
    return max(0, (civil_date(ctx.tx.timestamp) - civil_date(entity.registered_on)).days)


def new_company_many_payers(ctx: RuleContext) -> list[Signal]:
    signals = []
    seen: set[str] = set()
    for entity_id in (ctx.tx.receiver_id, ctx.tx.sender_id):
        if entity_id in seen:
            continue
        seen.add(entity_id)
        age = _company_age_days(ctx, entity_id)
        if age is None or age > 180:
            continue
        window_start = since(ctx.tx.timestamp, hours=24)
        incoming = [item for item in ctx.ledger.incoming(entity_id) if item.timestamp >= window_start]
        if ctx.tx.receiver_id == entity_id:
            incoming = incoming + [ctx.tx]
        payers = {item.sender_id for item in incoming}
        if len(payers) < 8:
            continue
        signals.append(
            _signal(
                "new_company_many_payers",
                Severity.HIGH,
                [LabelType.AML_LAUNDERING],
                (
                    f"A company aged {age} days received transfers from {len(payers)} "
                    "different counterparties within 24 hours."
                ),
                {"company_age_days": age, "distinct_payers": len(payers)},
            )
        )
    return signals


def declared_turnover_mismatch(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    revenue = tx.declared_annual_revenue
    if revenue is None or revenue <= 0:
        return []
    window_start = since(tx.timestamp, days=30)
    observed = tx.amount + sum(
        item.amount
        for item in ctx.ledger.prior
        if item.timestamp >= window_start and (item.sender_id == tx.sender_id or item.receiver_id == tx.sender_id)
    )
    monthly = revenue / 12
    ratio = observed / monthly
    if ratio < 3:
        return []
    severity = Severity.HIGH if ratio >= 5 else Severity.MEDIUM
    return [
        _signal(
            "declared_turnover_mismatch",
            severity,
            [LabelType.AML_LAUNDERING],
            (
                f"Observed 30-day bank flow is {ratio:.1f} times the monthly declared revenue "
                f"of {monthly:.0f} {tx.currency}."
            ),
            {"flow_to_monthly_revenue": round(ratio, 2)},
        )
    ]


def inactive_company_volume(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    status = (tx.company_status or "").lower()
    if status != "inactive" or tx.amount < 1000:
        return []
    return [
        _signal(
            "inactive_company_volume",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            f"{tx.sender_id} is inactive and moved {tx.amount:.0f} {tx.currency}.",
            {"amount": tx.amount, "status": status},
        )
    ]


def cross_border_flow(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    source = country_code(tx.country_from)
    destination = country_code(tx.country_to)
    if not source or not destination or source == destination or "TN" not in {source, destination}:
        return []
    if tx.amount < 20000:
        return []
    return [
        _signal(
            "cross_border_flow",
            Severity.MEDIUM,
            [],
            f"A {tx.amount:.0f} {tx.currency} payment moves between {source} and {destination}.",
            {"country_from": source, "country_to": destination},
        )
    ]


def foreign_card_presentment(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    channel = (tx.channel or "").lower()
    if channel not in {"card", "pos", "foreign_card"} or tx.amount < 2000:
        return []
    if country_code(tx.country_from) in (None, "TN"):
        return []
    return [
        _signal(
            "foreign_card_presentment",
            Severity.LOW,
            [LabelType.CARD_FRAUD],
            f"A {tx.amount:.0f} {tx.currency} card payment was presented outside Tunisia.",
            {"country_from": country_code(tx.country_from)},
        )
    ]
