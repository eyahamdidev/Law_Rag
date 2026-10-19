from __future__ import annotations

from fraud_detection.ledger import since
from fraud_detection.rules.context import RuleContext
from fraud_detection.rules.transaction_rules import _signal
from fraud_detection.schema import LabelType, Severity, Signal


def rapid_in_outflow(ctx: RuleContext) -> list[Signal]:
    tx = ctx.tx
    window_start = since(tx.timestamp, hours=6)
    incoming = [item for item in ctx.ledger.incoming(tx.sender_id) if item.timestamp >= window_start]
    if len(incoming) < 2:
        return []
    inflow = sum(item.amount for item in incoming)
    if inflow < 1000 or tx.amount / inflow < 0.70:
        return []
    payers = {item.sender_id for item in incoming}
    hours = (tx.timestamp - min(item.timestamp for item in incoming)).total_seconds() / 3600
    return [
        _signal(
            "rapid_in_outflow",
            Severity.HIGH,
            [LabelType.AML_LAUNDERING],
            (
                f"The account received {inflow:.0f} {tx.currency} from {len(payers)} counterparties "
                f"and sent {tx.amount / inflow:.0%} onward within {hours:.1f} hours."
            ),
            {
                "inflow_sum": round(inflow, 2),
                "outflow_ratio": round(tx.amount / inflow, 3),
                "distinct_payers": len(payers),
                "hours": round(hours, 2),
            },
        )
    ]
