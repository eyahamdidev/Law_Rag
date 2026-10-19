from __future__ import annotations

import math

from fraud_detection.ledger import Ledger, since
from fraud_detection.models.feature_stats import (
    amount_percentile,
    amount_to_old_balance,
    balance_mismatch_flag,
    balance_zeroed_flag,
    median_of,
)
from fraud_detection.normalize import country_code, local_hour
from fraud_detection.schema import EntityRecord

FEATURE_NAMES = [
    "log_amount",
    "amount",
    "hour",
    "is_night",
    "is_round_1000",
    "is_cross_border",
    "out_count_1h",
    "out_count_24h",
    "out_sum_24h",
    "in_count_24h",
    "in_sum_24h",
    "unique_in_counterparties_24h",
    "unique_out_counterparties_24h",
    "is_new_counterparty",
    "repeat_same_amount_72h",
    "hours_since_prev",
    "account_age_days",
    "amount_over_monthly_revenue",
    "is_foreign_receiver",
    "is_tnd",
    "in_out_ratio_6h",
    "bid_count",
    "award_to_estimate_ratio",
    "is_card",
    "has_invoice",
    "has_expense",
    "amount_vs_median",
    "amount_percentile",
    "out_count_7d",
    "balance_mismatch",
    "amount_to_old_balance",
    "balance_zeroed",
]


def feature_dict(ledger: Ledger, entities: dict[str, EntityRecord] | None = None) -> dict[str, float]:
    """Features use only the current row and earlier rows."""
    del entities
    tx = ledger.current
    outs = ledger.outgoing(tx.sender_id)
    ins = ledger.incoming(tx.sender_id)
    start_1h = since(tx.timestamp, hours=1)
    start_6h = since(tx.timestamp, hours=6)
    start_24h = since(tx.timestamp, hours=24)
    start_72h = since(tx.timestamp, hours=72)
    start_7d = since(tx.timestamp, days=7)
    outs_1h = [item for item in outs if item.timestamp >= start_1h]
    outs_24 = [item for item in outs if item.timestamp >= start_24h]
    outs_7d = [item for item in outs if item.timestamp >= start_7d]
    ins_24 = [item for item in ins if item.timestamp >= start_24h]
    ins_6 = [item for item in ins if item.timestamp >= start_6h]
    prior_amounts = [item.amount for item in outs]
    rounded_amount = int(round(tx.amount))
    same_amount = [
        item
        for item in outs
        if item.timestamp >= start_72h
        and item.receiver_id == tx.receiver_id
        and abs(int(round(item.amount)) - rounded_amount) <= 1
    ]
    hours_since = 720.0
    if outs:
        hours_since = min(720.0, (tx.timestamp - outs[-1].timestamp).total_seconds() / 3600)
    known_receivers = {item.receiver_id for item in outs}
    inflow = sum(item.amount for item in ins_6)
    revenue = tx.declared_annual_revenue or 0.0
    monthly = revenue / 12 if revenue else 0.0
    source = country_code(tx.country_from)
    destination = country_code(tx.country_to)
    hour = local_hour(tx.timestamp)
    age = float(tx.company_age_days) if tx.company_age_days is not None else -1.0
    typical = median_of(prior_amounts) if prior_amounts else 0.0
    return {
        "log_amount": math.log1p(tx.amount),
        "amount": float(tx.amount),
        "hour": float(hour),
        "is_night": 1.0 if hour >= 23 or hour <= 5 else 0.0,
        "is_round_1000": 1.0 if tx.amount >= 1000 and abs(tx.amount % 1000) <= 1e-6 else 0.0,
        "is_cross_border": 1.0 if source and destination and source != destination else 0.0,
        "out_count_1h": float(len(outs_1h)),
        "out_count_24h": float(len(outs_24)),
        "out_sum_24h": float(sum(item.amount for item in outs_24)),
        "in_count_24h": float(len(ins_24)),
        "in_sum_24h": float(sum(item.amount for item in ins_24)),
        "unique_in_counterparties_24h": float(len({item.sender_id for item in ins_24})),
        "unique_out_counterparties_24h": float(len({item.receiver_id for item in outs_24})),
        "is_new_counterparty": 0.0 if tx.receiver_id in known_receivers else 1.0,
        "repeat_same_amount_72h": float(len(same_amount)),
        "hours_since_prev": float(hours_since),
        "account_age_days": age,
        "amount_over_monthly_revenue": float(tx.amount / monthly) if monthly > 0 else 0.0,
        "is_foreign_receiver": 1.0 if destination not in (None, "TN") else 0.0,
        "is_tnd": 1.0 if tx.currency.upper() == "TND" else 0.0,
        "in_out_ratio_6h": float(min(5.0, tx.amount / inflow)) if inflow > 0 else 0.0,
        "bid_count": float(tx.bid_count or 0),
        "award_to_estimate_ratio": float(tx.award_to_estimate_ratio or 0),
        "is_card": 1.0 if (tx.channel or "").lower() in {"card", "pos", "foreign_card"} else 0.0,
        "has_invoice": 1.0 if tx.invoice_id else 0.0,
        "has_expense": 1.0 if tx.expense_id else 0.0,
        "amount_vs_median": float(tx.amount / typical) if typical else 1.0,
        "amount_percentile": amount_percentile(prior_amounts, tx.amount),
        "out_count_7d": float(len(outs_7d)),
        "balance_mismatch": balance_mismatch_flag(tx.old_balance, tx.new_balance, tx.amount),
        "amount_to_old_balance": amount_to_old_balance(tx.old_balance, tx.amount),
        "balance_zeroed": balance_zeroed_flag(tx.old_balance, tx.new_balance),
    }


def feature_row(ledger: Ledger, entities: dict[str, EntityRecord] | None = None) -> list[float]:
    """Replay earlier rows through the same incremental features used in training."""
    del entities
    from fraud_detection.models.online_features import OnlineFeatures

    online = OnlineFeatures()
    vector = [0.0] * len(FEATURE_NAMES)
    for item in ledger.all_rows:
        vector = online.transform_transaction(item)
    return vector
