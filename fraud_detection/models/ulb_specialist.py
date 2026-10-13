"""ULB credit-card specialist. It scores only when V1–V28 are present."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from fraud_detection.schema import Transaction


class ULBCardSpecialist:
    def __init__(self) -> None:
        self.model = None
        self.calibrator = None
        self.features: list[str] = []

    def score_transaction(self, transaction: Transaction) -> float | None:
        if self.model is None:
            return None
        pca = transaction.metadata.get("pca") if isinstance(transaction.metadata, dict) else None
        if not isinstance(pca, dict):
            return None
        values: list[float] = []
        for name in self.features:
            if name == "Amount":
                values.append(float(transaction.amount))
                continue
            raw = pca.get(name)
            if raw is None:
                return None
            values.append(float(raw))
        row = np.asarray([values], dtype=np.float32)
        probability = float(self.model.predict_proba(row)[0, 1])
        if self.calibrator is not None:
            probability = float(np.clip(self.calibrator.predict([probability])[0], 0.0, 1.0))
        return probability

    @classmethod
    def load(cls, path: str | Path) -> ULBCardSpecialist:
        payload = joblib.load(path)
        specialist = cls()
        specialist.model = payload["model"]
        specialist.calibrator = payload.get("calibrator")
        specialist.features = list(payload["features"])
        return specialist
