from __future__ import annotations

from fraud_detection.rules.aml_rules import rapid_in_outflow
from fraud_detection.rules.context import RuleContext
from fraud_detection.rules.entity_rules import pep_counterparty, unverified_company
from fraud_detection.rules.procurement_rules import high_award_ratio, short_submission_window, single_bid
from fraud_detection.rules.transaction_rules import (
    duplicate_payment,
    impossible_balance,
    new_counterparty_large,
    round_number_burst,
    structuring_just_below,
    sudden_geography_change,
    unusual_night_activity,
    unusual_velocity,
)
from fraud_detection.rules.tunisia_rules import (
    cross_border_flow,
    declared_turnover_mismatch,
    foreign_card_presentment,
    inactive_company_volume,
    new_company_many_payers,
    pass_through_account,
)
from fraud_detection.tunisia.ctaf_rules import CTAF_RULES
from fraud_detection.schema import Severity, Signal

RULES = [
    duplicate_payment,
    unusual_velocity,
    round_number_burst,
    structuring_just_below,
    unusual_night_activity,
    new_counterparty_large,
    sudden_geography_change,
    impossible_balance,
    rapid_in_outflow,
    pass_through_account,
    new_company_many_payers,
    declared_turnover_mismatch,
    inactive_company_volume,
    cross_border_flow,
    foreign_card_presentment,
    *CTAF_RULES,
    single_bid,
    high_award_ratio,
    short_submission_window,
    pep_counterparty,
    unverified_company,
]

_SEVERITY_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}


def dedupe_signals(signals: list[Signal]) -> list[Signal]:
    best: dict[str, Signal] = {}
    for signal in signals:
        current = best.get(signal.signal)
        if current is None or _SEVERITY_RANK[signal.severity] > _SEVERITY_RANK[current.severity]:
            best[signal.signal] = signal
    return sorted(best.values(), key=lambda item: (-_SEVERITY_RANK[item.severity], item.signal))


def run_rules(context: RuleContext) -> list[Signal]:
    found: list[Signal] = []
    for rule in RULES:
        found.extend(rule(context))
    return dedupe_signals(found)
