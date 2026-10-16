from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def _arrays(y_true, scores):
    labels = np.asarray(y_true).astype(int)
    values = np.asarray(scores, dtype=float)
    if len(labels) != len(values):
        raise ValueError("labels and scores must have the same length")
    return labels, values


def pr_auc(y_true, scores) -> float:
    labels, values = _arrays(y_true, scores)
    if labels.min() == labels.max():
        return float("nan")
    return float(average_precision_score(labels, values))


def precision_recall_f1(y_true, scores, threshold: float = 0.5) -> dict[str, float]:
    labels, values = _arrays(y_true, scores)
    predicted = (values >= threshold).astype(int)
    return {
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
    }


def recall_at_fpr(y_true, scores, max_fpr: float = 0.01) -> float:
    labels, values = _arrays(y_true, scores)
    negatives = max(1, int((labels == 0).sum()))
    positives = int((labels == 1).sum())
    if positives == 0:
        return float("nan")
    order = np.argsort(-values, kind="mergesort")
    false_positives = 0
    true_positives = 0
    best = 0.0
    for index in order:
        if labels[index] == 1:
            true_positives += 1
        else:
            false_positives += 1
        if false_positives / negatives <= max_fpr:
            best = true_positives / positives
        else:
            break
    return float(best)


def precision_at_k(y_true, scores, k: int) -> float:
    labels, values = _arrays(y_true, scores)
    if k <= 0:
        raise ValueError("k must be positive")
    k = min(k, len(labels))
    chosen = np.argsort(-values, kind="mergesort")[:k]
    return float(labels[chosen].mean())


def roc_auc(y_true, scores) -> float:
    labels, values = _arrays(y_true, scores)
    if labels.min() == labels.max():
        return float("nan")
    return float(roc_auc_score(labels, values))


def confusion_at_threshold(y_true, scores, threshold: float = 0.5) -> dict[str, int]:
    labels, values = _arrays(y_true, scores)
    predicted = (values >= threshold).astype(int)
    matrix = confusion_matrix(labels, predicted, labels=[0, 1])
    tn, fp, fn, tp = (int(matrix[0, 0]), int(matrix[0, 1]), int(matrix[1, 0]), int(matrix[1, 1]))
    negatives = max(1, tn + fp)
    return {
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "tp": tp,
        "false_positive_rate": float(fp / negatives),
    }


def recall_at_k(y_true, scores, k: int) -> float:
    labels, values = _arrays(y_true, scores)
    positives = int((labels == 1).sum())
    if positives == 0:
        return float("nan")
    if k <= 0:
        raise ValueError("k must be positive")
    k = min(k, len(labels))
    chosen = np.argsort(-values, kind="mergesort")[:k]
    return float(labels[chosen].sum() / positives)


def false_positives_per_thousand(y_true, scores, threshold: float) -> float:
    labels, values = _arrays(y_true, scores)
    predicted = values >= threshold
    false_positives = int(((predicted == 1) & (labels == 0)).sum())
    return 1000.0 * false_positives / max(1, len(labels))


def positive_prevalence(y_true) -> float:
    labels = np.asarray(y_true).astype(int)
    if len(labels) == 0:
        return float("nan")
    return float(labels.mean())


def pr_auc_lift(y_true, scores) -> dict[str, float]:
    """PR-AUC compared with the random baseline, which is the positive prevalence."""
    prevalence = positive_prevalence(y_true)
    area = pr_auc(y_true, scores)
    lift = float(area / prevalence) if prevalence and prevalence == prevalence and prevalence > 0 else float("nan")
    return {"positive_prevalence": prevalence, "pr_auc": area, "pr_auc_over_baseline": lift}


def brier_score(y_true, scores) -> float:
    labels, values = _arrays(y_true, scores)
    return float(np.mean((values - labels) ** 2))


def calibration_curve(y_true, scores, bins: int = 10) -> dict:
    """Equal-width reliability table and expected calibration error."""
    labels, values = _arrays(y_true, scores)
    values = np.clip(values, 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    ece = 0.0
    total = max(1, len(labels))
    for index in range(bins):
        lower = edges[index]
        upper = edges[index + 1]
        if index == bins - 1:
            mask = (values >= lower) & (values <= upper)
        else:
            mask = (values >= lower) & (values < upper)
        count = int(mask.sum())
        if count == 0:
            rows.append(
                {
                    "bin": index,
                    "lower": float(lower),
                    "upper": float(upper),
                    "count": 0,
                    "mean_predicted": None,
                    "observed_frequency": None,
                }
            )
            continue
        predicted = float(values[mask].mean())
        observed = float(labels[mask].mean())
        ece += (count / total) * abs(observed - predicted)
        rows.append(
            {
                "bin": index,
                "lower": float(lower),
                "upper": float(upper),
                "count": count,
                "mean_predicted": predicted,
                "observed_frequency": observed,
            }
        )
    return {"bins": rows, "expected_calibration_error": float(ece)}


def threshold_sweep(y_true, scores, thresholds: list[float] | None = None) -> list[dict]:
    labels, values = _arrays(y_true, scores)
    chosen = thresholds or [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    rows = []
    for threshold in chosen:
        point = precision_recall_f1(labels, values, threshold)
        point.update(confusion_at_threshold(labels, values, threshold))
        point["threshold"] = float(threshold)
        rows.append(point)
    return rows


def ranking_at_ks(y_true, scores, ks: list[int] | None = None) -> dict:
    labels, values = _arrays(y_true, scores)
    chosen = ks or [50, 100, 500]
    report = {}
    for k in chosen:
        if k > len(labels):
            report[f"precision_at_{k}"] = None
            report[f"recall_at_{k}"] = None
            report[f"k_{k}_available"] = False
            continue
        report[f"precision_at_{k}"] = precision_at_k(labels, values, k)
        report[f"recall_at_{k}"] = recall_at_k(labels, values, k)
        report[f"k_{k}_available"] = True
    return report


def classification_report(y_true, scores, threshold: float = 0.5, max_fpr: float = 0.01, top_k: int = 50) -> dict:
    base = precision_recall_f1(y_true, scores, threshold)
    base["pr_auc"] = pr_auc(y_true, scores)
    base["roc_auc"] = roc_auc(y_true, scores)
    base["recall_at_fpr"] = recall_at_fpr(y_true, scores, max_fpr)
    base["precision_at_k"] = precision_at_k(y_true, scores, top_k)
    base["recall_at_k"] = recall_at_k(y_true, scores, top_k)
    base["false_positives_per_1000"] = false_positives_per_thousand(y_true, scores, threshold)
    base.update(confusion_at_threshold(y_true, scores, threshold))
    return base
