"""Score held-out identities once, with the threshold frozen at training time.

    .venv/bin/python -m fraud_detection.evaluation.stamp_cnn_eval
"""

from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from fraud_detection.documents.stamp_cnn import (
    CHECKPOINT,
    average_precision,
    decision_counts,
    integration_decision,
    load_checkpoint,
    load_manifest,
    score_rows,
)
from fraud_detection.paths import EVAL

OUT = EVAL / "stamp_cnn_eval.json"
TEST_SCORES = EVAL / "stamp_cnn_test_scores.csv"
AUDIT = EVAL / "stamp_v3_audit.json"
LOCALIZATION = EVAL / "stamp_v3_localization.json"


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _slice_metrics(rows: list[dict], labels: np.ndarray, scores: np.ndarray, low: float, high: float) -> dict:
    counts = decision_counts(labels, scores, low, high)
    counts["average_precision"] = average_precision(labels, scores)
    counts["n"] = int(len(rows))
    return counts


def _grouped(rows, labels, scores, low, high, key: str) -> dict[str, dict]:
    buckets: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        buckets[row[key]].append(index)
    out = {}
    for name, indexes in sorted(buckets.items()):
        chosen = np.array(indexes)
        out[name] = _slice_metrics([rows[i] for i in chosen], labels[chosen], scores[chosen], low, high)
    return out


def _verifier_queries() -> list[dict]:
    """Latest reference-verifier verdicts. Localization rows replace the audit."""
    audit = json.loads(AUDIT.read_text())["agent"]["records"]
    fresh = {row["id"]: row for row in json.loads(LOCALIZATION.read_text())["records"]}
    merged = []
    for row in audit:
        if row["id"].endswith("_gen_000"):
            continue
        merged.append(fresh.get(row["id"], row))
    return merged


def _verifier_counts(rows: list[dict]) -> dict:
    labels = []
    decisions = []
    for row in rows:
        labels.append(0 if row["kind"] != "counterfeit" else 1)
        verdict = row["verdict"]
        if verdict == "fraudulent":
            decisions.append("suspicious")
        elif verdict == "genuine":
            decisions.append("likely_genuine")
        else:
            decisions.append("manual_review")
    # Reuse the decision counter by turning verdicts into extreme scores.
    scores = np.array(
        [1.0 if decision == "suspicious" else 0.0 if decision == "likely_genuine" else 0.5 for decision in decisions]
    )
    return decision_counts(np.array(labels), scores, 0.25, 0.75)


def _shortcut(rows: list[dict], labels: np.ndarray, scores: np.ndarray) -> dict:
    """Rank cues that are not the drawing. Measured after the model is frozen."""
    from fraud_detection.documents.stamp_cnn import DATASET

    jpeg = np.array([float(row["jpeg_q"]) for row in rows])
    sizes = []
    for row in rows:
        path = DATASET / row["image"]
        sizes.append(path.stat().st_size)
    file_bytes = np.array(sizes, dtype=np.float64)
    # Higher means more counterfeit-like, matching the classifier score direction.
    degraded = np.array([row["kind"] != "genuine" for row in rows])
    def _group(mask: np.ndarray) -> dict:
        return {
            "n": int(mask.sum()),
            "counterfeit_prevalence": float(labels[mask].mean()) if mask.any() else None,
            "model_average_precision": average_precision(labels[mask], scores[mask]),
            "lower_jpeg_quality_average_precision": average_precision(labels[mask], -jpeg[mask]),
            "smaller_file_average_precision": average_precision(labels[mask], -file_bytes[mask]),
        }

    synthetic = np.array([row["source_dataset"] == "v3" for row in rows])
    original = np.array([row["source_dataset"] == "v2" for row in rows])
    return {
        "queries_already_exclude_clean_reference": True,
        "all_queries": _group(np.ones(len(rows), dtype=bool)),
        "degraded_rows_only": _group(degraded),
        "new_synthetic": _group(synthetic),
        "originals": _group(original),
    }


def main() -> None:
    device = _device()
    model, payload = load_checkpoint(CHECKPOINT, device=device)
    low = float(payload["threshold_low"])
    high = float(payload["threshold_high"])
    rows = [row for row in load_manifest() if row["split"] == "test"]
    labels, scores = score_rows(model, rows, device=device)
    queries = [index for index, row in enumerate(rows) if not row["id"].endswith("_gen_000")]
    query_rows = [rows[index] for index in queries]
    query_labels = labels[queries]
    query_scores = scores[queries]
    synthetic = [index for index, row in enumerate(query_rows) if row["source_dataset"] == "v3"]
    original = [index for index, row in enumerate(query_rows) if row["source_dataset"] == "v2"]

    test_counts = _slice_metrics(query_rows, query_labels, query_scores, low, high)
    synthetic_counts = _slice_metrics(
        [query_rows[i] for i in synthetic], query_labels[synthetic], query_scores[synthetic], low, high
    )
    original_counts = _slice_metrics(
        [query_rows[i] for i in original], query_labels[original], query_scores[original], low, high
    )
    decision = integration_decision(test_counts, synthetic_counts, original_counts)
    verifier = _verifier_queries()
    result = {
        "checkpoint": str(CHECKPOINT),
        "version": payload["version"],
        "seed": payload["seed"],
        "threshold_high": high,
        "threshold_low": low,
        "threshold_source": "validation identities, target false-fraud quantile 0.05",
        "score_is_calibrated_probability": False,
        "queries_exclude_clean_reference": True,
        "classifier_queries": test_counts,
        "classifier_all_test_images_including_clean_reference": _slice_metrics(rows, labels, scores, low, high),
        "new_synthetic_identities": synthetic_counts,
        "original_identities": original_counts,
        "by_family": _grouped(query_rows, query_labels, query_scores, low, high, "family"),
        "by_identity": _grouped(query_rows, query_labels, query_scores, low, high, "identity_id"),
        "shortcut_probes": _shortcut(query_rows, query_labels, query_scores),
        "verifier_queries": _verifier_counts(verifier),
        "integration": decision,
        "val_average_precision": payload.get("val_average_precision"),
        "val_counts": payload.get("val_counts"),
    }
    OUT.write_text(json.dumps(result, indent=2))
    with TEST_SCORES.open("w", encoding="utf-8") as handle:
        handle.write("id,score\n")
        for row, score in zip(rows, scores):
            handle.write(f"{row['id']},{score:.6f}\n")
    print(json.dumps({
        "threshold_high": high,
        "threshold_low": low,
        "recall": test_counts["recall_count"],
        "false_fraud": test_counts["false_fraud_count"],
        "false_accept": test_counts["false_accept_count"],
        "precision": test_counts["precision"],
        "pr_auc": test_counts["average_precision"],
        "unresolved": test_counts["unresolved_count"],
        "synthetic_recall": synthetic_counts["recall_count"],
        "original_recall": original_counts["recall_count"],
        "integrate": decision["integrate"],
        "checks": decision["checks"],
    }, indent=2))


if __name__ == "__main__":
    main()
