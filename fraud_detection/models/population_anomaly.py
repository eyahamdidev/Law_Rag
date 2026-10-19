from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np

from fraud_detection.ledger import Ledger
from fraud_detection.models.features import FEATURE_NAMES, feature_row
from fraud_detection.schema import EntityRecord


class PopulationAnomaly:
    """Isolation Forest fit on legitimate behavioral feature rows.

    The returned score is 1 / (1 + exp(6 * decision_function)). Higher means
    more anomalous. decision_function is larger for inliers, so this maps
    typical rows toward 0 and outliers toward 1.
    """

    def __init__(self) -> None:
        self.model = None
        self.scaler = None
        self.feature_names = list(FEATURE_NAMES)

    def fit(self, features: np.ndarray):
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import RobustScaler

        matrix = np.asarray(features, dtype=np.float32)
        self.scaler = RobustScaler()
        scaled = self.scaler.fit_transform(matrix)
        self.model = IsolationForest(
            n_estimators=200,
            contamination=0.01,
            random_state=0,
            n_jobs=-1,
        )
        self.model.fit(scaled)
        return self

    def score_matrix(self, features: np.ndarray) -> np.ndarray:
        if self.model is None or self.scaler is None:
            raise RuntimeError("population anomaly model is not fitted")
        scaled = self.scaler.transform(np.asarray(features, dtype=np.float32))
        decision = self.model.decision_function(scaled)
        return 1.0 / (1.0 + np.exp(6.0 * decision))

    def score_ledger(self, ledger: Ledger, entities: dict[str, EntityRecord] | None = None) -> float | None:
        if self.model is None:
            return None
        if self.feature_names != list(FEATURE_NAMES):
            raise ValueError("anomaly model features do not match the current feature list; retrain")
        row = np.asarray([feature_row(ledger, entities)], dtype=np.float32)
        return float(self.score_matrix(row)[0])

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self.model, "scaler": self.scaler, "feature_names": self.feature_names},
            destination,
        )

    @classmethod
    def load(cls, path: str | Path) -> PopulationAnomaly:
        payload = joblib.load(path)
        detector = cls()
        detector.model = payload["model"]
        detector.scaler = payload["scaler"]
        detector.feature_names = payload["feature_names"]
        return detector


def isolation_score_from_decision(decision: float) -> float:
    return float(1.0 / (1.0 + math.exp(6.0 * decision)))
