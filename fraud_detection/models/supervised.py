from __future__ import annotations

import re
from pathlib import Path

import joblib
import numpy as np

from fraud_detection.ledger import Ledger, apply_entity_defaults
from fraud_detection.models.features import FEATURE_NAMES, feature_row
from fraud_detection.schema import EntityRecord, LabelType, Transaction

# Routing uses the fields on the transaction. The dataset name is not a feature
# and is not a routing key: an evaluator will not label the source.
_CARD_CHANNELS = frozenset({"card", "pos", "foreign_card"})
_CARD_TYPES = frozenset({"card", "payment_card", "pos", "credit_card", "debit_card", "credit card", "debit card"})
_CARD_QUALIFIERS = frozenset({"credit", "debit", "payment", "prepaid", "bank"})
_ACCOUNT_CHANNELS = frozenset({"mobile", "app", "ussd", "account"})
_MOBILE_MONEY_TYPES = frozenset({"cash_out", "cash_in", "debit"})
_AML_TYPES = frozenset(
    {"wire", "ach", "cheque", "check", "cash", "bitcoin", "crypto", "reinvestment", "sepa", "swift", "bank_transfer", "wire_transfer"}
)
_TRANSFER_TYPES = frozenset({"transfer"})


def _card_payment(channel: str, tx_type: str) -> bool:
    """Card routing uses the channel or a card payment type, not a substring.

    `gift_card_barter` contains the letters "card" and is not a card payment.
    `credit card` and `debit_card` are.
    """
    if channel in _CARD_CHANNELS or tx_type in _CARD_TYPES:
        return True
    tokens = {token for token in re.split(r"[^a-z0-9]+", tx_type) if token}
    return "card" in tokens and bool(tokens & _CARD_QUALIFIERS)


def _pca_ready(transaction: Transaction) -> bool:
    pca = transaction.metadata.get("pca") if isinstance(transaction.metadata, dict) else None
    if not isinstance(pca, dict):
        return False
    return all(pca.get(f"V{index}") is not None for index in range(1, 29))


def _balance_drain(transaction: Transaction) -> bool:
    """Account emptied by this payment. Absent balances are not a drain."""
    old = transaction.old_balance
    new = transaction.new_balance
    if old is None or new is None or old <= 0:
        return False
    zeroed = new <= max(1.0, 0.01 * old)
    emptied = transaction.amount >= 0.9 * old
    return bool(zeroed and emptied)


def eligible_supervised_types(transaction: Transaction) -> frozenset[str]:
    """One fraud family, chosen from the input shape.

    CARD_FRAUD requires card, payment-card, or a complete ULB PCA vector.
    ACCOUNT_TAKEOVER requires mobile-money, an account channel, a device, or
    an observed balance drain. AML_LAUNDERING requires a transfer or an AML
    payment format. Dataset names never select a head. Simulator balance
    features are therefore not applied to a card payment or a plain wire.
    """
    channel = (transaction.channel or "").strip().lower()
    tx_type = (transaction.transaction_type or "").strip().lower()
    card = _pca_ready(transaction) or _card_payment(channel, tx_type)
    if card:
        return frozenset({LabelType.CARD_FRAUD.value})
    account_access = (
        channel in _ACCOUNT_CHANNELS
        or tx_type in _MOBILE_MONEY_TYPES
        or bool(transaction.device_id)
        or _balance_drain(transaction)
    )
    if account_access:
        return frozenset({LabelType.ACCOUNT_TAKEOVER.value})
    if tx_type == "procurement" or transaction.bid_count is not None:
        return frozenset({LabelType.PROCUREMENT_RISK.value})
    if transaction.invoice_id:
        return frozenset({LabelType.INVOICE_FRAUD.value})
    if transaction.expense_id:
        return frozenset({LabelType.EXPENSE_FRAUD.value})
    if tx_type in _AML_TYPES or tx_type in _TRANSFER_TYPES:
        return frozenset({LabelType.AML_LAUNDERING.value})
    return frozenset()


def _fit_binary(features: np.ndarray, labels: np.ndarray):
    if len(set(labels.tolist())) < 2:
        return None
    try:
        import lightgbm as lgb

        model = lgb.LGBMClassifier(
            n_estimators=60,
            learning_rate=0.1,
            num_leaves=15,
            min_child_samples=5,
            subsample=0.9,
            colsample_bytree=0.9,
            class_weight="balanced",
            random_state=0,
            verbosity=-1,
        )
        model.fit(features, labels)
        return model
    except Exception:
        from sklearn.ensemble import HistGradientBoostingClassifier

        model = HistGradientBoostingClassifier(
            max_iter=60,
            learning_rate=0.1,
            random_state=0,
            class_weight="balanced",
        )
        model.fit(features, labels)
        return model


class SupervisedDetector:
    """One binary model per fraud type, plus a separate any-fraud model.

    Negatives for a type model are legitimate rows only. A card-fraud row is not
    treated as a clean AML example.
    """

    def __init__(self):
        self.binary = None
        self.by_type: dict[str, object] = {}
        self.calibrators: dict[str, object] = {}
        self.feature_names = list(FEATURE_NAMES)
        self.backend = "unfitted"
        self.type_threshold = 0.70

    def fit(
        self,
        rows: list[tuple[Transaction, LabelType | None]],
        entities: dict[str, EntityRecord] | None = None,
    ) -> SupervisedDetector:
        entity_map = entities or {}
        ordered = sorted(rows, key=lambda item: (item[0].timestamp, item[0].transaction_id))
        matrix: list[list[float]] = []
        targets: list[int] = []
        types: list[LabelType | None] = []
        history: list[Transaction] = []
        for transaction, label in ordered:
            enriched = apply_entity_defaults(transaction, entity_map)
            matrix.append(feature_row(Ledger(enriched, history), entity_map))
            targets.append(0 if label is None else 1)
            types.append(label)
            history.append(enriched)
        features = np.asarray(matrix, dtype=float)
        labels = np.asarray(targets)
        self.binary = _fit_binary(features, labels)
        self.by_type = {}
        for label in LabelType:
            positive = np.asarray([item == label for item in types])
            if int(positive.sum()) < 15:
                continue
            legitimate = np.asarray([item is None for item in types])
            keep = positive | legitimate
            type_labels = positive[keep].astype(int)
            fitted = _fit_binary(features[keep], type_labels)
            if fitted is not None:
                self.by_type[label.value] = fitted
        self.backend = "lightgbm" if self.binary is not None and self.binary.__class__.__module__.startswith("lightgbm") else "sklearn"
        return self

    def score(
        self,
        ledger: Ledger,
        entities: dict[str, EntityRecord] | None = None,
    ) -> tuple[float | None, list[LabelType], dict[str, float]]:
        if self.binary is None and not self.by_type:
            return None, [], {}
        row = np.asarray([feature_row(ledger, entities)], dtype=float)
        if self.feature_names != list(FEATURE_NAMES):
            raise ValueError("saved model features do not match the current feature list; retrain")
        allowed = eligible_supervised_types(ledger.current)
        by_type_scores: dict[str, float] = {}
        fired: list[LabelType] = []
        for name, model in self.by_type.items():
            if name not in allowed:
                continue
            raw = float(model.predict_proba(row)[0, 1])
            calibrator = self.calibrators.get(name)
            if calibrator is not None:
                probability = float(np.clip(calibrator.predict([raw])[0], 0.0, 1.0))
                cutoff = 0.50
            else:
                probability = raw
                cutoff = self.type_threshold
            by_type_scores[name] = probability
            if probability >= cutoff:
                fired.append(LabelType(name))
        if self.binary is not None:
            probability = float(self.binary.predict_proba(row)[0, 1])
        elif by_type_scores:
            probability = max(by_type_scores.values())
        else:
            probability = None
        return probability, fired, by_type_scores

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "binary": self.binary,
                "by_type": self.by_type,
                "feature_names": self.feature_names,
                "backend": self.backend,
                "calibrators": self.calibrators,
                "type_threshold": self.type_threshold,
            },
            destination,
        )

    @classmethod
    def load(cls, path: str | Path) -> SupervisedDetector:
        payload = joblib.load(path)
        detector = cls()
        detector.binary = payload["binary"]
        detector.by_type = payload["by_type"]
        detector.feature_names = payload["feature_names"]
        detector.backend = payload["backend"]
        detector.calibrators = payload.get("calibrators") or {}
        detector.type_threshold = float(payload.get("type_threshold", 0.70))
        return detector
