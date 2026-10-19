from __future__ import annotations

from fraud_detection.ledger import since
from fraud_detection.normalize import country_code
from fraud_detection.rules.context import RuleContext
from fraud_detection.rules.transaction_rules import _signal
from fraud_detection.schema import LabelType, Severity, Signal

_MONEY_ORDER_TOKENS = (
    "mandat",
    "money_order",
    "moneygram",
    "money_gram",
    "western_union",
)
_CASH_TOKENS = ("cash", "espece", "espèce", "atm", "dab", "gab", "withdrawal", "retrait")
_CHEQUE_TOKENS = ("cheque", "chèque", "check")
_IT_TOKENS = ("informat", "software", "it_service", "it service", "services informat")


def _blob(*parts: str | None) -> str:
    return " ".join(part.lower().replace("-", " ") for part in parts if part)


def _instrument(tx) -> str:
    metadata = tx.metadata or {}
    return _blob(tx.transaction_type, tx.channel, str(metadata.get("instrument") or ""))


def _is_money_order(tx) -> bool:
    text = _instrument(tx).replace(" ", "_")
    return any(token in text for token in _MONEY_ORDER_TOKENS)


def _is_cash(tx) -> bool:
    text = _instrument(tx)
    return any(token in text for token in _CASH_TOKENS)


def _is_cheque(tx) -> bool:
    text = _instrument(tx)
    return any(token in text for token in _CHEQUE_TOKENS)


def _cross_border(tx) -> bool:
    source = country_code(tx.country_from)
    destination = country_code(tx.country_to)
    if source and destination and source != destination:
        return True
    return bool((tx.metadata or {}).get("international_money_order"))


def _activity_text(ctx: RuleContext) -> str:
    metadata = ctx.tx.metadata or {}
    parts = [str(metadata.get("declared_activity") or "")]
    for entity_id in (ctx.tx.sender_id, ctx.tx.receiver_id):
        entity = ctx.entity(entity_id)
        if entity is not None and entity.activity:
            parts.append(entity.activity)
    return _blob(*parts)


def _cited(pattern_id: str, source_page: str, **evidence: object) -> dict:
    payload = {"pattern_id": pattern_id, "source_page": source_page, "confidence": "documented_case"}
    payload.update(evidence)
    return payload


def zero_declared_revenue_fan_in(ctx: RuleContext) -> list[Signal]:
    """CTAF-2024-T1: zero declared turnover against funding from many payers."""
    tx = ctx.tx
    if tx.declared_annual_revenue != 0:
        return []
    window_start = since(tx.timestamp, days=30)
    incoming = [item for item in ctx.ledger.incoming(tx.receiver_id) if item.timestamp >= window_start]
    incoming.append(tx)
    payers = {item.sender_id for item in incoming}
    if len(payers) < 5:
        return []
    return [
        _signal(
            "ctaf_zero_declared_revenue_fan_in",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                "CTAF 2024 typology 1: declared annual revenue is zero while several "
                f"distinct payers ({len(payers)}) funded this receiver within 30 days."
            ),
            _cited(
                "CTAF-2024-T1",
                "CTAF Rapport d'activité 2024, pp. 20-22",
                distinct_payers=len(payers),
            ),
        )
    ]


def synchronized_cash_or_cheque_pass_through(ctx: RuleContext) -> list[Signal]:
    """CTAF-2024-T2: cash or cheque deposits and a rapid onward movement."""
    tx = ctx.tx
    if not (_is_cash(tx) or _is_cheque(tx)):
        return []
    window_start = since(tx.timestamp, hours=6)
    incoming = [
        item
        for item in ctx.ledger.incoming(tx.sender_id)
        if item.timestamp >= window_start and (_is_cash(item) or _is_cheque(item))
    ]
    if len(incoming) < 2:
        return []
    inflow = sum(item.amount for item in incoming)
    if inflow <= 0 or tx.amount / inflow < 0.70:
        return []
    return [
        _signal(
            "ctaf_synchronized_cash_cheque",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                "CTAF 2024 typology 2: cash or cheque deposits and an onward payment "
                "covering most of that inflow happened within 6 hours."
            ),
            _cited(
                "CTAF-2024-T2",
                "CTAF Rapport d'activité 2024, pp. 22-23",
                inflow=round(inflow, 2),
                outflow_ratio=round(tx.amount / inflow, 3),
            ),
        )
    ]


def cross_border_pass_through(ctx: RuleContext) -> list[Signal]:
    """CTAF-2024-T3: foreign funds received and sent onward. Country alone is not enough."""
    tx = ctx.tx
    if not _cross_border(tx):
        return []
    window_start = since(tx.timestamp, hours=24)
    incoming = [
        item
        for item in ctx.ledger.incoming(tx.sender_id)
        if item.timestamp >= window_start and _cross_border(item)
    ]
    if len(incoming) < 2:
        return []
    inflow = sum(item.amount for item in incoming)
    if inflow <= 0 or tx.amount / inflow < 0.70:
        return []
    if country_code(tx.country_to) in (None, "TN") and country_code(tx.country_from) in (None, "TN"):
        return []
    return [
        _signal(
            "ctaf_cross_border_pass_through",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                "CTAF 2024 typology 3: cross-border funds were received and most of "
                "that amount was transferred onward within 24 hours."
            ),
            _cited(
                "CTAF-2024-T3",
                "CTAF Rapport d'activité 2024, pp. 23-25",
                distinct_originators=len({item.sender_id for item in incoming}),
                outflow_ratio=round(tx.amount / inflow, 3),
            ),
        )
    ]


def _betting_or_crypto(ctx: RuleContext) -> bool:
    metadata = ctx.tx.metadata or {}
    text = _blob(
        ctx.tx.merchant_category,
        ctx.tx.description,
        str(metadata.get("payment_purpose") or ""),
        str(metadata.get("activity_indicator") or ""),
    )
    tokens = ("betting", "sportsbook", "pari sportif", "paris sportif", "crypto", "cryptomonnaie")
    return any(token in text for token in tokens)


def betting_money_order_network(ctx: RuleContext) -> list[Signal]:
    """CTAF-2024-T4: money-order velocity plus an explicit betting or crypto indicator."""
    tx = ctx.tx
    if not _is_money_order(tx) or not _betting_or_crypto(ctx):
        return []
    window_start = since(tx.timestamp, days=30)
    related = [
        item
        for item in ctx.ledger.prior
        if item.timestamp >= window_start
        and _is_money_order(item)
        and tx.sender_id in {item.sender_id, item.receiver_id}
    ]
    related.append(tx)
    counterparties = {item.sender_id for item in related} | {item.receiver_id for item in related}
    counterparties.discard(tx.sender_id)
    if len(counterparties) < 4:
        return []
    return [
        _signal(
            "ctaf_betting_money_orders",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                "CTAF 2024 typology 4: money orders involve several counterparties and "
                "the payment itself carries a betting or crypto indicator."
            ),
            _cited(
                "CTAF-2024-T4",
                "CTAF Rapport d'activité 2024, pp. 25-26",
                distinct_counterparties=len(counterparties),
            ),
        )
    ]


def cyberfraud_occasional_money_orders(ctx: RuleContext) -> list[Signal]:
    """CTAF-2024-T5: occasional customer, several inbound money orders, short window."""
    tx = ctx.tx
    if not _is_money_order(tx):
        return []
    if (tx.metadata or {}).get("customer_relationship") != "occasional":
        return []
    window_start = since(tx.timestamp, days=7)
    incoming = [
        item
        for item in ctx.ledger.incoming(tx.receiver_id)
        if item.timestamp >= window_start and _is_money_order(item)
    ]
    incoming.append(tx)
    if len(incoming) < 3:
        return []
    return [
        _signal(
            "ctaf_cyberfraud_money_orders",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                "CTAF 2024 typology 5: an occasional customer received several money "
                f"orders ({len(incoming)}) within 7 days. The documented amount band "
                "was about 380 to 4000 TND; that band is not the trigger."
            ),
            _cited(
                "CTAF-2024-T5",
                "CTAF Rapport d'activité 2024, pp. 26-27",
                money_order_count=len(incoming),
            ),
        )
    ]


def declared_it_activity_cash_and_cross_border(ctx: RuleContext) -> list[Signal]:
    """CTAF-2024-T6: declared IT activity, cash funding, and a cross-border transfer."""
    activity = _activity_text(ctx)
    if not any(token in activity for token in _IT_TOKENS):
        return []
    window_start = since(ctx.tx.timestamp, days=30)
    account_ids = {ctx.tx.sender_id, ctx.tx.receiver_id}
    history = [
        item
        for item in ctx.ledger.prior
        if item.timestamp >= window_start and (item.sender_id in account_ids or item.receiver_id in account_ids)
    ]
    observed = history + [ctx.tx]
    has_cash = any(_is_cash(item) for item in observed)
    has_cross_border = any(_cross_border(item) for item in observed)
    if not (has_cash and has_cross_border):
        return []
    return [
        _signal(
            "ctaf_activity_mismatch_cash_cross_border",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                "CTAF 2024 typology 6: declared IT or software activity coincides with "
                "cash funding and a cross-border transfer in the same 30 days."
            ),
            _cited(
                "CTAF-2024-T6",
                "CTAF Rapport d'activité 2024, pp. 27-28",
                declared_activity=activity[:180],
            ),
        )
    ]


def repeated_international_money_orders(ctx: RuleContext) -> list[Signal]:
    """CTAF-2024-T7: many inbound cross-border money orders to one receiver."""
    tx = ctx.tx
    if not _is_money_order(tx) or not _cross_border(tx):
        return []
    window_start = since(tx.timestamp, days=120)
    incoming = [
        item
        for item in ctx.ledger.incoming(tx.receiver_id)
        if item.timestamp >= window_start and _is_money_order(item) and _cross_border(item)
    ]
    incoming.append(tx)
    if len(incoming) < 8:
        return []
    return [
        _signal(
            "ctaf_repeated_international_money_orders",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                "CTAF 2024 typology 7: this receiver collected "
                f"{len(incoming)} cross-border money orders in 120 days. The documented "
                "cases were 46 orders (76,445 TND, four months) and 57 orders "
                "(60,943.24 TND, eight months). Sender origin is not a condition."
            ),
            _cited(
                "CTAF-2024-T7",
                "CTAF Rapport d'activité 2024, pp. 28-29",
                money_order_count=len(incoming),
                documented_case_counts=[46, 57],
            ),
        )
    ]


CTAF_RULES = [
    zero_declared_revenue_fan_in,
    synchronized_cash_or_cheque_pass_through,
    cross_border_pass_through,
    betting_money_order_network,
    cyberfraud_occasional_money_orders,
    declared_it_activity_cash_and_cross_border,
    repeated_international_money_orders,
]
