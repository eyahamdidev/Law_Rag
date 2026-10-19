import pytest

from fraud_detection.data.synthetic_tunisia import find_example, generate_tunisia, history_before
from fraud_detection.entity_intelligence.registry import EntityRegistry
from fraud_detection.explanations.narrator import TemplateNarrator
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.models.supervised import SupervisedDetector
from fraud_detection.schema import Decision


@pytest.fixture(scope="module")
def population():
    return generate_tunisia()


@pytest.fixture(scope="module")
def engine(population):
    _, entities = population
    return FraudDetectionEngine(registry=EntityRegistry(entities))


def _score(engine, population, transaction_id: str):
    examples, entities = population
    current = next(item for item in examples if item.transaction.transaction_id == transaction_id)
    return current, engine.score(current.transaction, history_before(examples, transaction_id), entities)


def test_ordinary_supplier_payment_stays_low(engine, population):
    example, result = _score(engine, population, "normal-10-03")
    assert example.label_type is None
    assert result.decision == Decision.LOW_RISK
    assert result.risk_score < 45
    assert result.requires_human_review is False
    assert result.external_checks.entity_verified is True
    assert result.external_checks.sanctions is False


def test_pass_through_is_high_risk_aml(engine, population):
    _, result = _score(engine, population, "ring-0-out")
    assert result.decision == Decision.HIGH_RISK
    assert result.risk_score >= 75
    assert "pass_through_account" in result.fraud_types
    assert "rapid_in_outflow" in result.fraud_types
    assert "AML_LAUNDERING" in result.label_types
    assert "CARD_FRAUD" not in result.label_types
    assert "INVOICE_FRAUD" not in result.label_types
    assert result.model_scores.graph >= 0.7
    assert result.requires_human_review is True
    assert "counterparties" in result.explanation


def test_invoice_duplicate_is_not_labeled_as_laundering(engine, population):
    _, result = _score(engine, population, "inv-00-1")
    assert "duplicate_invoice" in result.fraud_types
    assert "INVOICE_FRAUD" in result.label_types
    assert "AML_LAUNDERING" not in result.label_types


def test_account_takeover_is_separate_from_aml(engine, population):
    _, result = _score(engine, population, "at-00-fraud")
    assert result.decision == Decision.HIGH_RISK
    assert "ACCOUNT_TAKEOVER" in result.label_types
    assert "AML_LAUNDERING" not in result.label_types
    assert "new_counterparty" in result.fraud_types


def test_closing_cycle_is_visible_to_the_graph(engine, population):
    _, result = _score(engine, population, "cycle-0-2")
    assert "cycle" in result.fraud_types
    assert result.model_scores.graph >= 0.9
    assert result.decision == Decision.HIGH_RISK


def test_narrator_cannot_change_the_score(population):
    examples, entities = population

    class RewritingNarrator:
        def narrate(self, transaction, signals):
            return "Fraud probability: 1%"

    engine = FraudDetectionEngine(registry=EntityRegistry(entities), narrator=RewritingNarrator())
    factual = FraudDetectionEngine(registry=EntityRegistry(entities), narrator=TemplateNarrator())
    current = find_example(examples, "pass_through_out")
    history = history_before(examples, current.transaction.transaction_id)
    rewritten = engine.score(current.transaction, history, entities)
    original = factual.score(current.transaction, history, entities)
    assert rewritten.explanation == "Fraud probability: 1%"
    assert rewritten.risk_score == original.risk_score
    assert rewritten.decision == original.decision
    assert rewritten.model_scores == original.model_scores


def test_supervised_ranks_pass_through_above_a_normal_payment(population):
    examples, entities = population
    entity_map = {entity.entity_id: entity for entity in entities}
    detector = SupervisedDetector().fit(
        [(item.transaction, item.label_type) for item in examples],
        entity_map,
    )
    engine = FraudDetectionEngine(supervised=detector, registry=EntityRegistry(entities))
    _, normal = _score(engine, population, "normal-10-03")
    _, fraud = _score(engine, population, "ring-0-out")
    assert normal.model_scores.supervised is not None
    assert fraud.model_scores.supervised is not None
    assert fraud.model_scores.supervised > normal.model_scores.supervised + 0.15
    assert normal.decision == Decision.LOW_RISK
