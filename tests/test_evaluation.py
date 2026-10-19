from datetime import datetime, timedelta

import numpy as np

from fraud_detection.evaluation.metrics import (
    brier_score,
    calibration_curve,
    positive_prevalence,
    pr_auc_lift,
    precision_at_k,
    pr_auc,
    ranking_at_ks,
    recall_at_fpr,
    threshold_sweep,
)
from fraud_detection.evaluation.splits import assert_time_order, holdout_entities, temporal_masks


def test_pr_auc_beats_a_constant_score_on_a_rare_positive_class():
    labels = [0] * 100 + [1]
    useful = [0.01] * 100 + [0.99]
    constant = [0.5] * 101
    assert pr_auc(labels, useful) > pr_auc(labels, constant)


def test_recall_at_fpr_and_precision_at_k():
    labels = np.asarray([0, 0, 0, 0, 1, 1])
    scores = np.asarray([0.1, 0.2, 0.05, 0.4, 0.9, 0.8])
    assert precision_at_k(labels, scores, k=2) == 1
    assert recall_at_fpr(labels, scores, max_fpr=0.0) == 1
    buried = np.asarray([0.99, 0.2, 0.05, 0.4, 0.9, 0.8])
    assert recall_at_fpr(labels, buried, max_fpr=0.0) == 0


def test_prevalence_lift_brier_and_threshold_sweep():
    labels = np.asarray([0, 0, 0, 0, 1])
    perfect = np.asarray([0.0, 0.0, 0.0, 0.1, 0.9])
    lift = pr_auc_lift(labels, perfect)
    assert positive_prevalence(labels) == 0.2
    assert lift["pr_auc_over_baseline"] > 1
    assert brier_score(labels, perfect) < brier_score(labels, np.full(5, 0.5))
    curve = calibration_curve(labels, perfect, bins=5)
    assert curve["expected_calibration_error"] >= 0
    sweep = threshold_sweep(labels, perfect, [0.5])
    assert sweep[0]["precision"] == 1
    ranking = ranking_at_ks(labels, perfect, [2, 50])
    assert ranking["precision_at_2"] == 0.5
    assert ranking["k_50_available"] is False


def test_temporal_split_does_not_leak_future_rows():
    start = datetime(2024, 1, 1)
    times = [start + timedelta(days=offset) for offset in range(100)]
    train, validation, test = temporal_masks(times, start + timedelta(days=60), start + timedelta(days=80))
    assert_time_order(times, train, validation, test)
    assert train.sum() == 60
    assert validation.sum() == 20
    assert test.sum() == 20


def test_entity_holdout_hides_training_accounts():
    ids = ["a", "a", "b", "c", "c", "d"]
    train, test = holdout_entities(ids, test_fraction=0.5, seed=1)
    assert set(np.asarray(ids)[train]).isdisjoint(set(np.asarray(ids)[test]))
    assert train.sum() + test.sum() == len(ids)
