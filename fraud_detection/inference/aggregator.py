from __future__ import annotations

from fraud_detection.schema import Decision, Severity, Signal

_WEIGHTS = {Severity.LOW: 0.35, Severity.MEDIUM: 0.62, Severity.HIGH: 0.90}


def rule_score(signals: list[Signal]) -> float:
    if not signals:
        return 0.0
    values = sorted(_WEIGHTS[signal.severity] for signal in signals)
    extras = sum(1 for value in values if value >= 0.62) - 1
    return min(1.0, values[-1] + 0.04 * max(0, extras))


def aggregate(
    *,
    rule_signals: list[Signal],
    supervised: float | None,
    anomaly: float | None,
    graph: float | None,
    sanctions: bool,
    coverage: str = "HIGH",
) -> tuple[int, Decision, float, bool]:
    """Evidence-aggregation policy. The returned 0-100 value is not a fraud probability.

    A quiet rule layer stays in the average so one model cannot hide it.
    The supervised floor applies only when coverage is HIGH and the calibrated
    specialist score is at least 0.90. Low coverage has already been
    down-weighted by the caller. A sanctions match is an independent floor.
    """
    rules = rule_score(rule_signals)
    parts: list[tuple[float, float]] = [(rules, 0.30)]
    model_values: list[float] = []
    if supervised is not None:
        parts.append((supervised, 0.30))
        model_values.append(supervised)
    if anomaly is not None:
        parts.append((anomaly, 0.20))
        model_values.append(anomaly)
    if graph is not None and graph > 0:
        parts.append((graph, 0.20))
        model_values.append(graph)
    weight = sum(item[1] for item in parts)
    score = sum(value * item_weight for value, item_weight in parts) / weight
    if rules >= 0.85:
        score = max(score, rules * 0.9)
    if supervised is not None and supervised >= 0.90 and coverage == "HIGH":
        score = max(score, 0.75)
    if graph is not None and graph >= 0.90:
        score = max(score, 0.75)
    strong_models = [value for value in model_values if value >= 0.80]
    if len(strong_models) >= 2:
        score = max(score, 0.78)
    if sanctions:
        score = max(score, 0.80)
    score = min(1.0, score)
    risk = int(round(100 * score))
    if risk >= 75:
        decision = Decision.HIGH_RISK
    elif risk >= 45:
        decision = Decision.MEDIUM_RISK
    else:
        decision = Decision.LOW_RISK

    values = [value for value, _ in parts]
    if len(values) < 2:
        confidence = 0.55
    else:
        spread = max(values) - min(values)
        confidence = max(0.35, min(0.95, 1.0 - spread))
    if sanctions:
        confidence = max(confidence, 0.80)
    confidence = round(confidence, 2)
    review = decision == Decision.HIGH_RISK or sanctions or (decision == Decision.MEDIUM_RISK and confidence < 0.70)
    return risk, decision, confidence, review
