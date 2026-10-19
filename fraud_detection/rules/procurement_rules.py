from __future__ import annotations

from fraud_detection.rules.context import RuleContext
from fraud_detection.rules.transaction_rules import _signal
from fraud_detection.schema import LabelType, Severity, Signal


def single_bid(ctx: RuleContext) -> list[Signal]:
    if ctx.tx.bid_count != 1:
        return []
    return [
        _signal(
            "single_bid",
            Severity.MEDIUM,
            [LabelType.PROCUREMENT_RISK],
            "The award received a single bid.",
            {"bid_count": 1},
        )
    ]


def high_award_ratio(ctx: RuleContext) -> list[Signal]:
    ratio = ctx.tx.award_to_estimate_ratio
    if ratio is None or ratio < 1.25:
        return []
    severity = Severity.HIGH if ratio >= 1.5 else Severity.MEDIUM
    return [
        _signal(
            "high_award_ratio",
            severity,
            [LabelType.PROCUREMENT_RISK],
            f"The award is {ratio:.2f} times the estimate.",
            {"award_to_estimate_ratio": ratio},
        )
    ]


def short_submission_window(ctx: RuleContext) -> list[Signal]:
    days = ctx.tx.submission_window_days
    if days is None or days > 5:
        return []
    return [
        _signal(
            "short_submission_window",
            Severity.MEDIUM,
            [LabelType.PROCUREMENT_RISK],
            f"Bidders had {days} days to respond.",
            {"submission_window_days": days},
        )
    ]
