from __future__ import annotations

from fraud_detection.inference.aggregator import rule_score
from fraud_detection.schema import ExternalChecks, ModelScores, Signal, Transaction, TunisiaLayer
from fraud_detection.tunisia.context import baseline_available, latest_channel_average
from fraud_detection.tunisia.country import detection_reasons

_HONESTY = (
    "No Tunisia transaction-level fraud model is loaded. tunisia_score is null. "
    "The final score is the existing global evidence policy, not a Tunisia probability."
)


def build_tunisia_layer(
    transaction: Transaction,
    *,
    rule_signals: list[Signal],
    model_scores: ModelScores,
    external_checks: ExternalChecks,
    risk_score: int,
    risk_label: str,
    sanctions_available: bool,
) -> TunisiaLayer:
    reasons = detection_reasons(transaction)
    if not reasons:
        return TunisiaLayer(
            country_detection="not_tunisian",
            coverage="NOT_APPLICABLE",
            model_status="not_applicable",
            explanations=[
                "Dataset name is not a Tunisia routing key. This payment has neither TND nor a TN country field."
            ],
        )
    context: dict = {}
    sources = ["ctaf_typologies_as_rules_not_labels", "global_evidence_policy"]
    if model_scores.supervised is not None:
        sources.append("global_supervised_model")
    if model_scores.anomaly is not None:
        sources.append(model_scores.anomaly_source or "anomaly")
    if sanctions_available:
        sources.append("sanctions_list")
    market = latest_channel_average(transaction.channel, transaction.transaction_type)
    coverage = "LOW"
    if baseline_available():
        coverage = "MEDIUM"
        sources.append("bct_payment_statistics_aggregate")
    if market is not None and transaction.currency.upper() == "TND" and market["average_value_tnd"]:
        ratio = transaction.amount / float(market["average_value_tnd"])
        market = {**market, "amount_vs_published_average": round(ratio, 3)}
        context["payment_market"] = market
    ctaf_hits = [item for item in rule_signals if str(item.evidence.get("pattern_id", "")).startswith("CTAF-")]
    if ctaf_hits:
        sources.append("ctaf_2024_documented_cases")
        context["ctaf_pattern_ids"] = [str(item.evidence.get("pattern_id")) for item in ctaf_hits]
    explanations = [
        "Tunisia routing used " + ", ".join(reasons) + ".",
        _HONESTY,
        (
            "Tunisia coverage is MEDIUM when published BCT payment aggregates are available, "
            "and LOW when they are not. HIGH is reserved for a model trained on real labeled "
            "Tunisian transactions, which this system does not have."
        ),
    ]
    if market and "amount_vs_published_average" in market:
        explanations.append(
            "Amount is "
            f"{market['amount_vs_published_average']:.2f} times the published BCT average "
            f"for {market['published_channel']} in {market['period']}. "
            "That ratio is context from an aggregate table, not a fraud label."
        )
    elif transaction.channel or transaction.transaction_type:
        explanations.append(
            "No published BCT channel average was applied. ATM, TPE-only, and cash-withdrawal "
            "series are not separate rows in the downloaded payment table."
        )
    sanctions_score = _sanctions_score(external_checks, sanctions_available)
    rules = rule_score([item for item in rule_signals if item.signal not in {"sanctions_match", "sanctions_possible_match"}])
    return TunisiaLayer(
        country="TN",
        country_detection=";".join(reasons),
        coverage=coverage,
        global_score=model_scores.supervised,
        tunisia_score=None,
        anomaly_score=model_scores.anomaly,
        sanctions_score=sanctions_score,
        rule_score=round(rules, 4),
        final_score=risk_score,
        risk_label=risk_label,
        specialist=None,
        explanations=explanations,
        data_sources_used=sources,
        model_trained=False,
        model_status="not_trained_no_transaction_labels",
        context=context,
    )


def _sanctions_score(external_checks: ExternalChecks, sanctions_available: bool) -> float | None:
    if not sanctions_available or external_checks.sanctions_status in {"not_available", "no_name_supplied"}:
        return None
    if external_checks.sanctions_status == "match":
        if external_checks.match_score is None:
            return 1.0
        return external_checks.match_score
    if external_checks.sanctions_status == "possible_match":
        return external_checks.match_score
    if external_checks.sanctions_status == "no_match":
        return 0.0
    return None
