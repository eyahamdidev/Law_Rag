"""Unsupervised behavior model on portable features only.

This is not a fraud-type classifier. It scores whether a transaction is unusual
relative to legitimate public-data rows, without using dataset identity or
PaySim balance-drain columns.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from fraud_detection.ledger import Ledger
from fraud_detection.models.features import feature_row
from fraud_detection.models.portable import PORTABLE_FEATURES, portable_indices
from fraud_detection.schema import EntityRecord


class GeneralBehavior:
    def __init__(self) -> None:
        self.model = None
        self.scaler = None
        self.feature_names = list(PORTABLE_FEATURES)
        self.bounds: list[tuple[float, float]] = []

    def fit(self, portable_matrix: np.ndarray) -> GeneralBehavior:
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import RobustScaler

        matrix = np.nan_to_num(np.asarray(portable_matrix, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        self.scaler = RobustScaler()
        scaled = self.scaler.fit_transform(matrix)
        self.model = IsolationForest(
            n_estimators=200,
            contamination=0.01,
            random_state=0,
            n_jobs=-1,
        )
        self.model.fit(scaled)
        low = np.quantile(matrix, 0.01, axis=0)
        high = np.quantile(matrix, 0.99, axis=0)
        self.bounds = [(float(left), float(right)) for left, right in zip(low, high)]
        return self

    def score_matrix(self, portable_matrix: np.ndarray) -> np.ndarray:
        if self.model is None or self.scaler is None:
            raise RuntimeError("general behavior model is not fitted")
        matrix = np.nan_to_num(np.asarray(portable_matrix, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        scaled = self.scaler.transform(matrix)
        decision = self.model.decision_function(scaled)
        return 1.0 / (1.0 + np.exp(6.0 * decision))

    def score_ledger(self, ledger: Ledger, entities: dict[str, EntityRecord] | None = None) -> float | None:
        if self.model is None:
            return None
        full = feature_row(ledger, entities)
        indexes = portable_indices()
        row = np.asarray([[full[index] for index in indexes]], dtype=np.float32)
        return float(self.score_matrix(row)[0])

    def portable_values(self, ledger: Ledger, entities: dict[str, EntityRecord] | None = None) -> list[float]:
        full = feature_row(ledger, entities)
        indexes = portable_indices()
        return [float(full[index]) for index in indexes]

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "scaler": self.scaler,
                "feature_names": self.feature_names,
                "bounds": self.bounds,
            },
            destination,
        )

    @classmethod
    def load(cls, path: str | Path) -> GeneralBehavior:
        payload = joblib.load(path)
        model = cls()
        model.model = payload["model"]
        model.scaler = payload["scaler"]
        model.feature_names = list(payload["feature_names"])
        model.bounds = [tuple(item) for item in payload.get("bounds") or []]
        if model.feature_names != list(PORTABLE_FEATURES):
            raise ValueError("general behavior features do not match the portable feature list; retrain")
        return model
