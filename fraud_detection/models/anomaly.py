from __future__ import annotations

import math
import statistics

import numpy as np
from sklearn.ensemble import IsolationForest

from fraud_detection.ledger import Ledger
from fraud_detection.normalize import local_hour
from fraud_detection.schema import EntityRecord, LabelType, Severity, Signal, Transaction


def _cheap_matrix(rows: list[Transaction]) -> np.ndarray:
    amounts = [row.amount for row in rows]
    matrix = []
    for index, row in enumerate(rows):
        previous = amounts[:index]
        typical = statistics.median(previous) if previous else row.amount
        gap = 720.0
        if index:
            gap = min(720.0, (row.timestamp - rows[index - 1].timestamp).total_seconds() / 3600)
        matrix.append(
            [
                math.log1p(row.amount),
                float(local_hour(row.timestamp)),
                float(row.amount / typical) if typical else 0.0,
                gap,
            ]
        )
    return np.asarray(matrix, dtype=float)


def _mad_score(history: list[float], current: float) -> float:
    typical = statistics.median(history)
    deviation = statistics.median(abs(amount - typical) for amount in history)
    if deviation < 1e-9:
        if typical <= 0:
            return 0.0
        return float(min(1.0, abs(current - typical) / typical / 4))
    z_score = 0.6745 * (current - typical) / deviation
    if z_score <= 0:
        return 0.05
    return float(min(1.0, z_score / 8))


def _isolation_score(history: list[Transaction], current: Transaction) -> float | None:
    ordered = sorted(history, key=lambda item: (item.timestamp, item.transaction_id))
    matrix = _cheap_matrix(ordered + [current])
    baseline = matrix[:-1]
    keep = baseline.var(axis=0) > 1e-8
    if int(keep.sum()) == 0:
        return None
    model = IsolationForest(
        n_estimators=100,
        contamination=0.02,
        random_state=0,
        n_jobs=1,
    )
    model.fit(baseline[:, keep])
    decision = float(model.decision_function(matrix[-1:, keep])[0])
    return float(1 / (1 + math.exp(6 * decision)))


def score_anomaly(
    ledger: Ledger,
    entities: dict[str, EntityRecord] | None = None,
) -> tuple[float | None, Signal | None]:
    del entities
    prior = ledger.outgoing(ledger.current.sender_id)
    if len(prior) >= 25:
        risk = _isolation_score(prior, ledger.current)
        if risk is None:
            risk = _mad_score([item.amount for item in prior], ledger.current.amount)
    elif len(prior) >= 8:
        risk = _mad_score([item.amount for item in prior], ledger.current.amount)
    else:
        return None, None
    signal = None
    if risk >= 0.75:
        severity = Severity.HIGH if risk >= 0.90 else Severity.MEDIUM
        signal = Signal(
            signal="transaction_anomaly",
            severity=severity,
            label_types=[LabelType.ANOMALY],
            detail=(
                f"The amount is unusual for this sender compared with their own history "
                f"(anomaly score {risk:.2f})."
            ),
            evidence={"anomaly": round(risk, 3)},
        )
    return risk, signal
