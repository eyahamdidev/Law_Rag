from __future__ import annotations

from typing import Protocol

from fraud_detection.schema import Severity, Signal, Transaction


class Narrator(Protocol):
    def narrate(self, transaction: Transaction, signals: list[Signal]) -> str:
        """Describe the evidence. Implementations must not return a score."""


class TemplateNarrator:
    """Turns rule and graph evidence into a factual explanation."""

    def narrate(self, transaction: Transaction, signals: list[Signal]) -> str:
        if not signals:
            return (
                f"No rule, graph pattern, sanctions hit, or entity alert fired for "
                f"{transaction.transaction_id}."
            )
        ordered = sorted(signals, key=lambda item: {"high": 0, "medium": 1, "low": 2}[_severity(item)])
        sentences = [item.detail.strip().rstrip(".") + "." for item in ordered[:4]]
        return " ".join(sentences)


def evidence_bundle(transaction: Transaction, signals: list[Signal], risk_score: int, decision: str) -> dict:
    """Payload for an external LLM. The score is an input, not something the model may set."""
    return {
        "instruction": "Explain why this transaction was flagged. Do not invent or change the risk score.",
        "risk_score": risk_score,
        "decision": decision,
        "transaction": {
            "transaction_id": transaction.transaction_id,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "sender_id": transaction.sender_id,
            "receiver_id": transaction.receiver_id,
            "timestamp": transaction.timestamp.isoformat(),
        },
        "signals": [
            {"signal": item.signal, "severity": _severity(item), "detail": item.detail, "evidence": item.evidence}
            for item in signals
        ],
    }


def _severity(signal: Signal) -> str:
    if isinstance(signal.severity, Severity):
        return signal.severity.value
    return str(signal.severity)
