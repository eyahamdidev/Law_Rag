import json

import joblib
import pytest

from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.models.population_anomaly import PopulationAnomaly
from fraud_detection.models.supervised import SupervisedDetector
from fraud_detection.paths import ARTIFACTS, EVAL, RAW
from fraud_detection.schema import Transaction


pytestmark = pytest.mark.skipif(
    not (ARTIFACTS / "supervised.joblib").exists(),
    reason="trained artifacts are produced by python -m fraud_detection train",
)


def test_trained_model_scores_a_real_paysim_request():
    request_path = EVAL / "demo_paysim_request.json"
    if not request_path.exists():
        pytest.skip("demo request is written at the end of training")
    payload = json.loads(request_path.read_text())
    current = Transaction.model_validate(payload["transaction"])
    history = [Transaction.model_validate(item) for item in payload["history"]]
    anomaly_path = ARTIFACTS / "anomaly.joblib"
    engine = FraudDetectionEngine(
        supervised=SupervisedDetector.load(ARTIFACTS / "supervised.joblib"),
        population_anomaly=PopulationAnomaly.load(anomaly_path) if anomaly_path.exists() else None,
    )
    result = engine.score(current, history)
    assert result.model_scores.supervised is not None
    assert 0 <= result.risk_score <= 100
    assert result.risk_level == result.decision.value
    assert result.model_scores.anomaly_source == "population_isolation_forest"
    assert payload["data_origin"] == "REAL_PUBLIC_DATA"
    scores = result.model_scores.supervised_by_type
    assert set(scores) == {"ACCOUNT_TAKEOVER"}
    assert "CARD_FRAUD" not in result.label_types
    assert "AML_LAUNDERING" not in result.label_types
    assert "ACCOUNT_TAKEOVER" in result.label_types


def test_sanctions_name_check_does_not_inherit_card_fraud():
    request_path = EVAL / "demo_sanctions_request.json"
    if not request_path.exists():
        pytest.skip("sanctions demo request is not on disk")
    payload = json.loads(request_path.read_text())
    current = Transaction.model_validate(payload["transaction"])
    sanctions_path = ARTIFACTS / "sanctions.joblib"
    if not sanctions_path.exists():
        pytest.skip("sanctions index is produced by training")
    sanctions = joblib.load(sanctions_path)
    if not isinstance(sanctions, SanctionsIndex):
        pytest.skip("sanctions artifact is not an index")
    engine = FraudDetectionEngine(
        supervised=SupervisedDetector.load(ARTIFACTS / "supervised.joblib"),
        sanctions=sanctions,
    )
    result = engine.score(current, [])
    assert result.external_checks.sanctions is True
    assert result.external_checks.sanctions_status == "match"
    assert result.risk_score >= 75
    assert "CARD_FRAUD" not in result.label_types
    assert "CARD_FRAUD" not in result.model_scores.supervised_by_type
    assert "ACCOUNT_TAKEOVER" not in result.model_scores.supervised_by_type
    aml = result.model_scores.supervised_by_type.get("AML_LAUNDERING")
    assert aml is None or aml < 0.5


def test_raw_banksim_header_is_present():
    header = (RAW / "banksim" / "bs140513_032310.csv").read_text(encoding="utf-8", errors="replace").splitlines()[0]
    assert "fraud" in header
    assert "customer" in header
