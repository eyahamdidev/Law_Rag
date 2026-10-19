"""Measure the saved specialists, then try a small validation-only LightGBM pass.

The test split is scored for the report. It is not used to choose a threshold,
a feature set, or a hyperparameter configuration.

    .venv/bin/python -m fraud_detection.evaluation.diagnose_models
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from fraud_detection.evaluation.metrics import (
    brier_score,
    calibration_curve,
    classification_report,
    pr_auc,
    pr_auc_lift,
    precision_at_k,
    ranking_at_ks,
    threshold_sweep,
)
from fraud_detection.models.features import FEATURE_NAMES
from fraud_detection.models.supervised import SupervisedDetector
from fraud_detection.paths import ARTIFACTS, EVAL, PROCESSED, RAW

THRESHOLDS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
TAIL = 0.30
CANDIDATES = {
    "current": {
        "n_estimators": 200,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": -1,
        "min_child_samples": 50,
        "min_split_gain": 0.0,
        "colsample_bytree": 0.8,
        "subsample": 0.8,
        "reg_alpha": 0.0,
        "reg_lambda": 0.0,
    },
    "regularized": {
        "n_estimators": 400,
        "learning_rate": 0.03,
        "num_leaves": 31,
        "max_depth": 8,
        "min_child_samples": 80,
        "min_split_gain": 0.05,
        "colsample_bytree": 0.8,
        "subsample": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
    },
    "shallow": {
        "n_estimators": 200,
        "learning_rate": 0.05,
        "num_leaves": 15,
        "max_depth": 6,
        "min_child_samples": 100,
        "min_split_gain": 0.1,
        "colsample_bytree": 0.7,
        "subsample": 0.9,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
    },
    "wider": {
        "n_estimators": 300,
        "learning_rate": 0.05,
        "num_leaves": 63,
        "max_depth": 8,
        "min_child_samples": 40,
        "min_split_gain": 0.0,
        "colsample_bytree": 0.7,
        "subsample": 0.8,
        "reg_alpha": 0.0,
        "reg_lambda": 0.5,
    },
}
BEHAVIORAL = (
    ("CARD_FRAUD", "banksim", PROCESSED / "banksim_features.npz"),
    ("ACCOUNT_TAKEOVER", "paysim", PROCESSED / "paysim_features.npz"),
    ("AML_LAUNDERING", "ibm_aml", PROCESSED / "ibm_aml_features.npz"),
)
COMPATIBILITY = {
    ("banksim", "banksim"): ("compatible", "Same card-payment simulator and feature matrix."),
    ("paysim", "paysim"): ("compatible", "Same mobile-money simulator and feature matrix."),
    ("ibm_aml", "ibm_aml"): ("compatible", "Same AML simulator and feature matrix."),
    ("banksim", "paysim"): (
        "incompatible",
        "BankSim fraud is a card payment. PaySim fraud is an account drain. Balance columns are empty on BankSim and decisive on PaySim.",
    ),
    ("paysim", "banksim"): (
        "incompatible",
        "A balance-drain model does not describe a card payment that has no balances.",
    ),
    ("banksim", "ibm_aml"): (
        "partially compatible",
        "Amount, hour, and counterparty counts exist on both. The labels are card fraud versus laundering, and IBM has no card PCA.",
    ),
    ("ibm_aml", "banksim"): (
        "partially compatible",
        "Shared behavioral columns only. A laundering head is not a card-fraud detector.",
    ),
    ("paysim", "ibm_aml"): (
        "partially compatible",
        "Both are account-to-account flows. PaySim's drain features are zero on IBM, and IBM's label is not an account drain.",
    ),
    ("ibm_aml", "paysim"): (
        "partially compatible",
        "Shared flow counts. PaySim positives are defined by emptying the account, which this head was not trained to detect.",
    ),
}
PROFILE_FEATURES = (
    "log_amount",
    "amount_vs_median",
    "hour",
    "is_night",
    "out_count_1h",
    "out_count_24h",
    "in_count_24h",
    "unique_out_counterparties_24h",
    "unique_in_counterparties_24h",
    "is_new_counterparty",
    "hours_since_prev",
    "in_out_ratio_6h",
    "repeat_same_amount_72h",
    "is_card",
    "is_foreign_receiver",
    "balance_mismatch",
    "amount_to_old_balance",
    "balance_zeroed",
)


def _sanitize(value):
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return round(number, 6)
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, np.ndarray):
        return _sanitize(value.tolist())
    return value


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_sanitize(payload), indent=2) + "\n")


def _score(model, calibrator, features: np.ndarray, chunk: int = 200_000) -> np.ndarray:
    if len(features) == 0:
        return np.zeros(0, dtype=float)
    parts = []
    for start in range(0, len(features), chunk):
        raw = model.predict_proba(features[start : start + chunk])[:, 1]
        if calibrator is not None:
            raw = np.clip(calibrator.predict(raw), 0.0, 1.0)
        parts.append(np.asarray(raw, dtype=float))
    return np.concatenate(parts)


def _split_report(labels: np.ndarray, scores: np.ndarray, *, role: str) -> dict:
    report = classification_report(labels, scores, threshold=0.5, top_k=100)
    report.update(pr_auc_lift(labels, scores))
    report["brier"] = brier_score(labels, scores)
    report["calibration"] = calibration_curve(labels, scores)
    report["ranking"] = ranking_at_ks(labels, scores, [50, 100, 500])
    if role == "validation":
        report["threshold_sweep"] = threshold_sweep(labels, scores, THRESHOLDS)
        report["threshold_selection"] = "reported only; the live cutoff stays 0.50 and was not chosen from this sweep or from the test set"
    else:
        report["threshold_sweep"] = None
        report["threshold_selection"] = "not used for any decision"
    report["role"] = role
    return report


def _mean_profile(features: np.ndarray, mask: np.ndarray) -> dict:
    if int(mask.sum()) == 0:
        return {}
    block = features[mask]
    profile = {}
    for name in PROFILE_FEATURES:
        column = block[:, FEATURE_NAMES.index(name)]
        profile[name] = float(np.mean(column))
    return profile


def _top_rows(features: np.ndarray, labels: np.ndarray, scores: np.ndarray, *, positive: bool, limit: int = 8) -> list[dict]:
    mask = labels == (1 if positive else 0)
    indexes = np.flatnonzero(mask)
    if len(indexes) == 0:
        return []
    order = indexes[np.argsort(-scores[indexes], kind="mergesort")][:limit]
    rows = []
    for index in order:
        row = {"score": float(scores[index]), "label": int(labels[index])}
        for name in ("log_amount", "amount_vs_median", "out_count_1h", "out_count_24h", "in_count_24h", "hours_since_prev", "is_new_counterparty", "balance_zeroed"):
            row[name] = float(features[index, FEATURE_NAMES.index(name)])
        rows.append(row)
    return rows


def _validation_tail(count: int) -> int:
    return int(count * (1.0 - TAIL))


def _fit_candidate(train_x, train_y, early_x, early_y, params: dict):
    import lightgbm as lgb

    model = lgb.LGBMClassifier(
        class_weight="balanced",
        random_state=0,
        verbosity=-1,
        n_jobs=4,
        **params,
    )
    if len(early_y) > 20 and len(np.unique(early_y)) > 1:
        model.fit(
            train_x,
            train_y,
            eval_set=[(early_x, early_y)],
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )
    else:
        model.fit(train_x, train_y)
    return model


def _candidate_row(model, tail_x, tail_y) -> dict:
    scores = _score(model, None, tail_x)
    lift = pr_auc_lift(tail_y, scores)
    operating = classification_report(tail_y, scores, threshold=0.5, top_k=min(100, len(tail_y)))
    return {
        "best_iteration": int(getattr(model, "best_iteration_", 0) or model.n_estimators),
        "validation_tail_pr_auc": lift["pr_auc"],
        "validation_tail_prevalence": lift["positive_prevalence"],
        "validation_tail_pr_auc_over_baseline": lift["pr_auc_over_baseline"],
        "validation_tail_roc_auc": operating["roc_auc"],
        "validation_tail_precision": operating["precision"],
        "validation_tail_recall": operating["recall"],
        "validation_tail_f1": operating["f1"],
        "validation_tail_fpr": operating["false_positive_rate"],
        "validation_tail_precision_at_100": operating["precision_at_k"],
    }


def _hard_negative_matrix(train_x, train_y, baseline):
    """Keep every training positive, the hardest legitimate rows, and a matched easy sample."""
    raw = _score(baseline, None, train_x)
    positives = np.flatnonzero(train_y == 1)
    negatives = np.flatnonzero(train_y == 0)
    if len(negatives) < 100:
        return None
    hard_count = max(1_000, len(negatives) // 5)
    hard = negatives[np.argsort(-raw[negatives], kind="mergesort")[:hard_count]]
    easy_pool = np.setdiff1d(negatives, hard, assume_unique=False)
    rng = np.random.default_rng(0)
    easy_count = min(len(easy_pool), hard_count)
    easy = rng.choice(easy_pool, size=easy_count, replace=False) if easy_count else np.array([], dtype=int)
    chosen = np.concatenate([positives, hard, easy])
    rng.shuffle(chosen)
    return train_x[chosen], train_y[chosen], {"hard_negatives": int(len(hard)), "easy_negatives": int(len(easy)), "positives": int(len(positives))}


def diagnose_behavioral(detector: SupervisedDetector) -> tuple[dict, dict, dict]:
    reports = {}
    tuning = {}
    matrices = {}
    for label, dataset, path in BEHAVIORAL:
        print(f"score {label}", flush=True)
        bundle = np.load(path)
        train_x = np.nan_to_num(bundle["train_x"], nan=0.0, posinf=0.0, neginf=0.0)
        train_y = bundle["train_y"].astype(int)
        val_x = np.nan_to_num(bundle["val_x"], nan=0.0, posinf=0.0, neginf=0.0)
        val_y = bundle["val_y"].astype(int)
        test_x = np.nan_to_num(bundle["test_x"], nan=0.0, posinf=0.0, neginf=0.0)
        test_y = bundle["test_y"].astype(int)
        bundle.close()
        model = detector.by_type[label]
        calibrator = detector.calibrators.get(label)
        val_scores = _score(model, calibrator, val_x)
        test_scores = _score(model, calibrator, test_x)
        predicted = val_scores >= 0.5
        tp = (predicted == 1) & (val_y == 1)
        fp = (predicted == 1) & (val_y == 0)
        fn = (predicted == 0) & (val_y == 1)
        tn = (predicted == 0) & (val_y == 0)
        reports[label] = {
            "dataset": dataset,
            "model": "saved artifact, not refit",
            "calibration_note": (
                "Isotonic regression was fit on a 200k validation slice that includes every validation positive. "
                "Validation calibration is therefore partly in-sample. Test calibration was not used to fit or select anything."
            ),
            "validation": _split_report(val_y, val_scores, role="validation"),
            "test": _split_report(test_y, test_scores, role="test"),
            "validation_error_counts": {
                "tp": int(tp.sum()),
                "fp": int(fp.sum()),
                "fn": int(fn.sum()),
                "tn": int(tn.sum()),
            },
            "validation_feature_means": {
                "true_positive": _mean_profile(val_x, tp),
                "false_negative": _mean_profile(val_x, fn),
                "false_positive": _mean_profile(val_x, fp),
                "true_negative": _mean_profile(val_x, tn),
            },
            "validation_top_true_positives": _top_rows(val_x, val_y, val_scores, positive=True),
            "validation_top_false_positives": _top_rows(val_x, val_y, val_scores, positive=False),
            "feature_importance": [
                {"feature": FEATURE_NAMES[int(index)], "gain": int(gain)}
                for index, gain in enumerate(getattr(model, "feature_importances_", []))
                if int(gain) > 0
            ],
        }
        reports[label]["feature_importance"] = sorted(reports[label]["feature_importance"], key=lambda item: -item["gain"])[:12]
        cut = _validation_tail(len(val_y))
        matrices[label] = {
            "dataset": dataset,
            "train_x": train_x,
            "train_y": train_y,
            "early_x": val_x[:cut],
            "early_y": val_y[:cut],
            "tail_x": val_x[cut:],
            "tail_y": val_y[cut:],
            "saved_tail_pr_auc": pr_auc(val_y[cut:], val_scores[cut:]),
        }
        del val_x, test_x, val_scores, test_scores
        print(f"  test PR-AUC {reports[label]['test']['pr_auc']:.4f} prevalence {reports[label]['test']['positive_prevalence']:.6f}", flush=True)
    return reports, tuning, matrices


def tune_behavioral(matrices: dict) -> dict:
    tuning = {}
    for label, data in matrices.items():
        print(f"tune {label} on validation tail", flush=True)
        rows = {}
        fitted = {}
        for name, params in CANDIDATES.items():
            model = _fit_candidate(data["train_x"], data["train_y"], data["early_x"], data["early_y"], params)
            rows[name] = _candidate_row(model, data["tail_x"], data["tail_y"])
            fitted[name] = model
            print(f"  {name} tail PR-AUC {rows[name]['validation_tail_pr_auc']:.4f}", flush=True)
        if label == "AML_LAUNDERING":
            mined = _hard_negative_matrix(data["train_x"], data["train_y"], fitted["current"])
            if mined is not None:
                mined_x, mined_y, mined_counts = mined
                mined_model = _fit_candidate(mined_x, mined_y, data["early_x"], data["early_y"], CANDIDATES["current"])
                rows["hard_negative_mining"] = _candidate_row(mined_model, data["tail_x"], data["tail_y"])
                rows["hard_negative_mining"]["training_mix"] = mined_counts
                print(f"  hard_negative_mining tail PR-AUC {rows['hard_negative_mining']['validation_tail_pr_auc']:.4f}", flush=True)
        best_name = max(rows, key=lambda name: rows[name]["validation_tail_pr_auc"])
        current_area = rows["current"]["validation_tail_pr_auc"]
        best_area = rows[best_name]["validation_tail_pr_auc"]
        gain = best_area - current_area
        precision_drop = rows["current"]["validation_tail_precision"] - rows[best_name]["validation_tail_precision"]
        adopt = best_name != "current" and gain >= 0.02 and precision_drop <= 0.05
        tuning[label] = {
            "selection_split": "chronological last 30% of validation; early stopping used only the first 70%",
            "test_set_used": False,
            "saved_model_pr_auc_on_same_tail": data["saved_tail_pr_auc"],
            "saved_model_note": "The saved model was early-stopped on a random validation slice, so this tail number can be slightly optimistic for the saved model.",
            "candidates": rows,
            "best_on_validation_tail": best_name,
            "pr_auc_gain_vs_refit_current": gain,
            "adopt": adopt,
            "adopt_rule": "Adopt only if the validation-tail PR-AUC gain is at least 0.02 and precision at 0.50 does not fall by more than 0.05.",
        }
        del fitted
    return tuning


def diagnose_ulb() -> dict:
    import pandas as pd

    payload = __import__("joblib").load(ARTIFACTS / "ulb_card.joblib")
    frame = pd.read_csv(RAW / "ulb" / "creditcard.csv")
    frame = frame.sort_values("Time", kind="mergesort")
    time = frame["Time"].to_numpy()
    labels = frame["Class"].astype(int).to_numpy()
    columns = payload["features"]
    features = np.nan_to_num(frame[columns].to_numpy(dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    del frame
    count = len(labels)
    train_end = time[int((count - 1) * 0.70)]
    val_end = time[int((count - 1) * 0.85)]
    validation = (time > train_end) & (time <= val_end)
    test = time > val_end
    train = time <= train_end
    scores_val = _score(payload["model"], payload["calibrator"], features[validation])
    scores_test = _score(payload["model"], payload["calibrator"], features[test])
    cut = _validation_tail(int(validation.sum()))
    val_x = features[validation]
    val_y = labels[validation]
    print("tune ULB on validation tail", flush=True)
    candidates = {}
    for name, params in CANDIDATES.items():
        model = _fit_candidate(features[train], labels[train], val_x[:cut], val_y[:cut], params)
        candidates[name] = _candidate_row(model, val_x[cut:], val_y[cut:])
        print(f"  {name} tail PR-AUC {candidates[name]['validation_tail_pr_auc']:.4f}", flush=True)
    best_name = max(candidates, key=lambda name: candidates[name]["validation_tail_pr_auc"])
    gain = candidates[best_name]["validation_tail_pr_auc"] - candidates["current"]["validation_tail_pr_auc"]
    precision_drop = candidates["current"]["validation_tail_precision"] - candidates[best_name]["validation_tail_precision"]
    return {
        "dataset": "ulb_creditcard",
        "compatibility_with_behavioral_heads": "incompatible",
        "compatibility_reason": "ULB inputs are V1-V28 and Amount. The behavioral heads use payment history, not PCA columns.",
        "validation": _split_report(val_y, scores_val, role="validation"),
        "test": _split_report(labels[test], scores_test, role="test"),
        "tuning": {
            "selection_split": "chronological last 30% of the ULB validation window",
            "test_set_used": False,
            "candidates": candidates,
            "best_on_validation_tail": best_name,
            "pr_auc_gain_vs_refit_current": gain,
            "adopt": best_name != "current" and gain >= 0.02 and precision_drop <= 0.05,
            "adopt_rule": "Adopt only if the validation-tail PR-AUC gain is at least 0.02 and precision at 0.50 does not fall by more than 0.05.",
        },
    }


def cross_dataset(detector: SupervisedDetector) -> list[dict]:
    loaded = {}
    for label, dataset, path in BEHAVIORAL:
        bundle = np.load(path)
        loaded[dataset] = (
            label,
            np.nan_to_num(bundle["val_x"], nan=0.0, posinf=0.0, neginf=0.0),
            bundle["val_y"].astype(int),
        )
        bundle.close()
    rows = []
    for source_label, source_name, _path in BEHAVIORAL:
        model = detector.by_type[source_label]
        calibrator = detector.calibrators.get(source_label)
        for target_name, (target_label, features, labels) in loaded.items():
            kind, reason = COMPATIBILITY[(source_name, target_name)]
            scores = _score(model, calibrator, features)
            lift = pr_auc_lift(labels, scores)
            rows.append(
                {
                    "model": source_label,
                    "trained_on": source_name,
                    "scored_on": target_name,
                    "scored_label": target_label,
                    "compatibility": kind,
                    "reason": reason,
                    "pr_auc": lift["pr_auc"],
                    "positive_prevalence": lift["positive_prevalence"],
                    "pr_auc_over_baseline": lift["pr_auc_over_baseline"],
                }
            )
            print(f"cross {source_name}->{target_name} {kind} PR-AUC {lift['pr_auc']:.4f}", flush=True)
    return rows


def main() -> None:
    detector = SupervisedDetector.load(ARTIFACTS / "supervised.joblib")
    behavioral, _empty, matrices = diagnose_behavioral(detector)
    tuning = tune_behavioral(matrices)
    del matrices
    ulb = diagnose_ulb()
    cross = cross_dataset(detector)
    payload = {
        "protocol": {
            "train": "fit",
            "validation": "threshold table, calibration description, and the only split used to compare candidates",
            "test": "final measurement of the saved models; not used to choose a threshold, feature, or hyperparameter",
            "current_pipeline_history": (
                "The saved models use one fixed LightGBM configuration. Early stopping and isotonic calibration used a validation slice. "
                "Published test metrics were not used to pick among hyperparameter candidates, because no candidate search had been run."
            ),
            "live_threshold": 0.50,
        },
        "behavioral": behavioral,
        "tuning": tuning,
        "ulb": ulb,
        "cross_dataset": cross,
        "features_changed": False,
    }
    destination = EVAL / "operating_points.json"
    _write(destination, payload)
    print(f"wrote {destination}", flush=True)


if __name__ == "__main__":
    main()
