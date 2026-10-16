"""Test that evaluates the deterministic rules engine on the 32 labelled profiles."""

import json
from pathlib import Path

from app.modules.aid.rules_engine import detect_law_handoff, match_programs
from app.schemas.aid import AidProfile

DATASET_PATH = Path(__file__).parents[1] / "app" / "eval" / "datasets" / "aid_profiles.jsonl"


def test_labelled_profiles_dataset_exists_and_has_at_least_30():
    """Verify deliverable requirement: at least 30 labelled profiles."""
    assert DATASET_PATH.exists()
    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]
    assert len(lines) >= 30


def test_dataset_exact_match_against_rules_engine():
    """Evaluate accuracy, precision, and recall of deterministic rule engine on the dataset."""
    assert DATASET_PATH.exists()
    records = []
    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))

    exact_matches = 0
    total_expected = 0
    total_predicted = 0
    total_true_positives = 0

    for item in records:
        if item.get("is_statute_handoff"):
            handoff = detect_law_handoff(item["query"])
            assert handoff is not None
            assert handoff.to == "law"
            exact_matches += 1
            continue

        profile = AidProfile(
            stage=item.get("stage", "unspecified"),
            sector=item.get("sector", ""),
            need=item.get("need", "unspecified"),
            funding_need_tnd=item.get("funding_need_tnd"),
            governorate=item.get("governorate"),
            is_innovative=item.get("is_innovative"),
            has_startup_label=item.get("has_startup_label"),
            is_graduate=item.get("is_graduate"),
            free_text=item.get("query"),
        )
        res = match_programs(profile)
        pred_ids = set(p.id for p in res["eligible_programs"])
        expected_ids = set(item.get("expected_programs", []))

        if pred_ids == expected_ids:
            exact_matches += 1

        tp = len(pred_ids & expected_ids)
        total_true_positives += tp
        total_predicted += len(pred_ids)
        total_expected += len(expected_ids)

    precision = total_true_positives / total_predicted if total_predicted else 1.0
    recall = total_true_positives / total_expected if total_expected else 1.0
    exact_match_rate = exact_matches / len(records)

    print(
        f"\nDataset Evaluation Results: Exact Match={exact_match_rate:.2%}, "
        f"Precision={precision:.2%}, Recall={recall:.2%}"
    )

    assert exact_match_rate == 1.0, f"Expected 100% exact match on deterministic rules, got {exact_match_rate:.2%}"
    assert precision == 1.0
    assert recall == 1.0

