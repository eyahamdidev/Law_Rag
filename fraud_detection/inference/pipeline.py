from __future__ import annotations

import numpy as np

from fraud_detection.entity_intelligence.registry import EntityRegistry
from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.explanations.narrator import Narrator, TemplateNarrator
from fraud_detection.inference.aggregator import aggregate
from fraud_detection.ledger import Ledger, apply_entity_defaults
from fraud_detection.models.anomaly import score_anomaly
from fraud_detection.models.features import feature_row
from fraud_detection.models.general_behavior import GeneralBehavior
from fraud_detection.models.graph import analyze_graph
from fraud_detection.models.population_anomaly import PopulationAnomaly
from fraud_detection.models.portable import assess_coverage, portable_indices
from fraud_detection.models.supervised import SupervisedDetector
from fraud_detection.models.ulb_specialist import ULBCardSpecialist
from fraud_detection.rules import dedupe_signals, run_rules
from fraud_detection.tunisia.assess import build_tunisia_layer
from fraud_detection.rules.context import RuleContext
from fraud_detection.rules.entity_rules import sanctions_signals
from fraud_detection.schema import (
    EntityRecord,
    ExternalChecks,
    FraudAssessment,
    LabelType,
    ModelScores,
    SignalView,
    Transaction,
)


class FraudDetectionEngine:
    """Score one transaction. The narrator receives the result and cannot change it."""

    def __init__(
        self,
        supervised: SupervisedDetector | None = None,
        sanctions: SanctionsIndex | None = None,
        registry: EntityRegistry | None = None,
        narrator: Narrator | None = None,
        population_anomaly: PopulationAnomaly | None = None,
        general_behavior: GeneralBehavior | None = None,
        ulb_specialist: ULBCardSpecialist | None = None,
    ):
        self.supervised = supervised
        self.sanctions = sanctions or SanctionsIndex([])
        self.registry = registry or EntityRegistry([])
        self.narrator = narrator or TemplateNarrator()
        self.population_anomaly = population_anomaly
        self.general_behavior = general_behavior
        self.ulb_specialist = ulb_specialist

    def score(
        self,
        transaction: Transaction,
        history: list[Transaction] | None = None,
        entities: list[EntityRecord] | None = None,
    ) -> FraudAssessment:
        registry = self.registry.overlay(entities or [])
        enriched = apply_entity_defaults(transaction, registry.by_id).model_copy(update={"label_type": None})
        ledger = Ledger(enriched, history or [])
        context = RuleContext(ledger, registry.by_id, registry.loaded)
        rule_hits = run_rules(context) + sanctions_signals(enriched, self.sanctions)
        rule_hits = dedupe_signals(rule_hits)
        graph_score, graph_hits, graph_status = analyze_graph(ledger)
        entity_anomaly, anomaly_hit = score_anomaly(ledger, registry.by_id)
        anomaly_score = entity_anomaly
        anomaly_source = "entity_history" if entity_anomaly is not None else None
        if self.population_anomaly is not None:
            population_score = self.population_anomaly.score_ledger(ledger, registry.by_id)
            if population_score is not None:
                anomaly_score = population_score
                anomaly_source = "population_isolation_forest"
        supervised_score = None
        supervised_labels: list[LabelType] = []
        supervised_by_type: dict[str, float] = {}
        specialist_sources: dict[str, str] = {}
        if self.supervised is not None:
            supervised_score, supervised_labels, supervised_by_type = self.supervised.score(ledger, registry.by_id)
            specialist_sources = {name: "behavioral" for name in supervised_by_type}
        pca_present = isinstance(enriched.metadata.get("pca"), dict) and bool(enriched.metadata.get("pca"))
        if self.ulb_specialist is not None and ("CARD_FRAUD" in specialist_sources or pca_present):
            ulb_score = self.ulb_specialist.score_transaction(enriched)
            if ulb_score is not None:
                supervised_by_type["CARD_FRAUD"] = ulb_score
                specialist_sources["CARD_FRAUD"] = "ulb_creditcard"
                supervised_labels = [label for label in supervised_labels if label != LabelType.CARD_FRAUD]
                if ulb_score >= 0.50:
                    supervised_labels.append(LabelType.CARD_FRAUD)
                if self.supervised is None or self.supervised.binary is None:
                    supervised_score = max(supervised_by_type.values()) if supervised_by_type else ulb_score
        general_score = None
        portable_values = None
        bounds = None
        if self.supervised is not None or self.general_behavior is not None:
            full = feature_row(ledger, registry.by_id)
            indexes = portable_indices()
            portable_values = [float(full[index]) for index in indexes]
        if self.general_behavior is not None and portable_values is not None:
            general_score = float(self.general_behavior.score_matrix(np.asarray([portable_values], dtype=np.float32))[0])
            bounds = self.general_behavior.bounds
        coverage, outside = assess_coverage(enriched, portable_values, bounds)
        blend_supervised = supervised_score
        if coverage == "LOW" and blend_supervised is not None:
            blend_supervised = blend_supervised * 0.45
            supervised_labels = []
        if general_score is not None and anomaly_score is not None:
            if general_score > anomaly_score:
                anomaly_source = "general_behavior"
            anomaly_score = max(anomaly_score, general_score)
        elif general_score is not None:
            anomaly_score = general_score
            anomaly_source = "general_behavior"

        displayed = dedupe_signals(rule_hits + graph_hits + ([anomaly_hit] if anomaly_hit else []))
        sanctions_hit = any(item.signal == "sanctions_match" for item in rule_hits)
        sanctions_possible = any(item.signal == "sanctions_possible_match" for item in rule_hits)
        risk, decision, confidence, review = aggregate(
            rule_signals=[
                item
                for item in rule_hits
                if item.signal not in {"sanctions_match", "sanctions_possible_match"}
            ],
            supervised=blend_supervised,
            anomaly=anomaly_score,
            graph=graph_score if graph_status == "scored" else 0.0,
            sanctions=sanctions_hit,
            coverage=coverage,
        )
        fraud_types: list[str] = []
        label_types: list[str] = []
        for item in displayed:
            if item.signal not in fraud_types:
                fraud_types.append(item.signal)
            for label in item.label_types:
                if label.value not in label_types:
                    label_types.append(label.value)
        for label in supervised_labels:
            if label.value not in label_types:
                label_types.append(label.value)
        if supervised_labels and "supervised_type_match" not in fraud_types:
            fraud_types.append("supervised_type_match")

        lists = []
        matched_list = None
        matched_entity = None
        match_score = None
        for item in rule_hits:
            if item.signal not in {"sanctions_match", "sanctions_possible_match"}:
                continue
            list_name = str(item.evidence.get("list_name", ""))
            if list_name and list_name not in lists:
                lists.append(list_name)
            candidate = item.evidence.get("match_score")
            if match_score is None or (candidate is not None and float(candidate) >= match_score):
                matched_list = list_name or None
                matched_entity = item.evidence.get("matched_name")
                match_score = None if candidate is None else float(candidate)
        names_supplied = bool(enriched.sender_name or enriched.receiver_name)
        if not self.sanctions.available:
            sanctions_status = "not_available"
        elif not names_supplied:
            sanctions_status = "no_name_supplied"
        elif sanctions_hit:
            sanctions_status = "match"
        elif sanctions_possible:
            sanctions_status = "possible_match"
        else:
            sanctions_status = "no_match"
        if sanctions_hit:
            model_confidence = max(confidence, 0.80)
        elif coverage == "LOW":
            model_confidence = 0.35
            confidence = min(confidence, 0.35)
        elif coverage == "MEDIUM":
            model_confidence = 0.55
            confidence = min(confidence, 0.60)
        elif supervised_score is not None and supervised_score >= 0.90:
            model_confidence = max(confidence, 0.80)
        else:
            model_confidence = max(confidence, 0.70)
        confidence = round(confidence, 2)
        model_confidence = round(float(model_confidence), 2)
        explanation = self.narrator.narrate(enriched, displayed)
        evidence = [item.detail for item in displayed]
        for name, probability in supervised_by_type.items():
            source = specialist_sources.get(name, "behavioral")
            evidence.append(f"Supervised {name} calibrated score {probability:.3f} from {source}.")
        if general_score is not None:
            evidence.append(f"General behavior score {general_score:.3f}.")
        if anomaly_score is not None:
            evidence.append(f"Anomaly score {anomaly_score:.3f} from {anomaly_source}.")
        evidence.append(f"Data coverage {coverage}. Portable features outside training bounds: {outside}.")
        if coverage == "LOW":
            evidence.append("Specialist labels were withheld because coverage is low.")
        if graph_status == "insufficient_history":
            evidence.append("Graph status insufficient_history.")
        elif graph_score > 0:
            evidence.append(f"Graph score {graph_score:.3f}.")
        entity_verified = _entities_verified(enriched, registry)
        rounded_types = {name: round(probability, 4) for name, probability in supervised_by_type.items()}
        model_scores = ModelScores(
            supervised=None if supervised_score is None else round(supervised_score, 4),
            anomaly=None if anomaly_score is None else round(anomaly_score, 4),
            graph=round(graph_score, 4),
            supervised_by_type=rounded_types,
            anomaly_source=anomaly_source,
            general_behavior=None if general_score is None else round(general_score, 4),
            specialist_sources=specialist_sources,
        )
        external = ExternalChecks(
            sanctions=sanctions_hit,
            entity_verified=entity_verified,
            sanctions_lists=lists,
            sanctions_status=sanctions_status,
            matched_list=matched_list,
            matched_entity=None if matched_entity is None else str(matched_entity),
            match_score=None if match_score is None else round(match_score, 4),
        )
        tunisia = build_tunisia_layer(
            enriched,
            rule_signals=rule_hits,
            model_scores=model_scores,
            external_checks=external,
            risk_score=risk,
            risk_label=decision.value,
            sanctions_available=self.sanctions.available,
        )
        if tunisia.country == "TN":
            evidence.append(
                "Tunisia coverage "
                f"{tunisia.coverage}. tunisia_score is null because no real labeled Tunisian transactions were available."
            )
        return FraudAssessment(
            risk_score=risk,
            decision=decision,
            fraud_types=fraud_types,
            label_types=label_types,
            signals=[
                SignalView(signal=item.signal, severity=item.severity.value, detail=item.detail)
                for item in displayed
            ],
            model_scores=model_scores,
            external_checks=external,
            confidence=confidence,
            requires_human_review=review,
            explanation=explanation,
            risk_level=decision.value,
            evidence=evidence,
            data_coverage=coverage,
            model_confidence=model_confidence,
            graph_status=graph_status,
            tunisia=tunisia,
            entity_checks={
                "sanctions_status": sanctions_status,
                "sanctions_match": sanctions_hit,
                "matched_list": matched_list,
                "matched_entity": None if matched_entity is None else str(matched_entity),
                "match_score": None if match_score is None else round(match_score, 4),
                "entity_verified": entity_verified,
            },
        )


def _entities_verified(transaction: Transaction, registry: EntityRegistry) -> bool:
    if not registry.loaded:
        return False
    return registry.get(transaction.sender_id) is not None and registry.get(transaction.receiver_id) is not None

