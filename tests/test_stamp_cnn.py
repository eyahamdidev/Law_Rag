"""The ResNet baseline stays off the live verdict path.

Preprocessing and the three-way decision are tested without a full training
run. The checkpoint test loads the saved file when that file is part of the
tree.
"""

import inspect

import numpy as np
import pytest
from PIL import Image

from fraud_detection.documents.stamp_cnn import (
    CHECKPOINT,
    DATASET,
    augment_pil,
    crop_stamp,
    decide,
    decision_counts,
    integration_decision,
    label_of,
    letterbox,
    load_manifest,
    predict_image,
    thresholds_from_scores,
)
from fraud_detection.schema import DocumentMark


def test_manifest_labels_and_the_identity_split():
    from fraud_detection.documents.stamp_cnn import assert_identity_split

    rows = load_manifest()
    assert_identity_split(rows)
    assert label_of("counterfeit") == 1
    assert label_of("genuine") == 0
    assert label_of("genuine_variant") == 0
    kinds = {row["kind"] for row in rows}
    assert kinds == {"genuine", "genuine_variant", "counterfeit"}


def test_crop_is_deterministic_and_keeps_a_dark_mark():
    page = np.full((80, 120, 3), 250, dtype=np.uint8)
    page[20:60, 30:90] = 20
    first = crop_stamp(page)
    second = crop_stamp(page)
    assert np.array_equal(first, second)
    assert first.shape[0] <= page.shape[0]
    assert first.shape[1] <= page.shape[1]
    assert int(first.mean()) < 200


def test_letterbox_preserves_aspect_inside_the_square():
    image = Image.new("RGB", (100, 40), (0, 0, 0))
    boxed = letterbox(image, 224)
    assert boxed.size == (224, 224)
    assert boxed.getpixel((112, 112)) == (0, 0, 0)
    assert boxed.getpixel((0, 0)) == (255, 255, 255)


def test_augmentation_does_not_change_the_canvas_size():
    image = Image.new("RGB", (60, 40), (10, 20, 30))
    import random

    edited = augment_pil(image, random.Random(0))
    assert edited.size == image.size
    assert edited.mode == "RGB"


def test_thresholds_come_from_the_two_score_lists_only():
    genuine = np.linspace(0.0, 0.4, 21)
    counterfeit = np.linspace(0.2, 1.0, 21)
    high, low = thresholds_from_scores(genuine, counterfeit, target_fpr=0.05)
    assert 0.0 <= low <= high <= 1.0
    assert high == pytest.approx(float(np.quantile(genuine, 0.95)))


def test_three_way_counts_do_not_call_review_fraud():
    labels = np.array([0, 0, 1, 1, 1])
    scores = np.array([0.1, 0.9, 0.95, 0.5, 0.05])
    counts = decision_counts(labels, scores, low=0.2, high=0.8)
    assert decide(0.5, 0.2, 0.8) == "manual_review"
    assert counts["matrix"]["genuine"]["suspicious"] == 1
    assert counts["matrix"]["counterfeit"]["suspicious"] == 1
    assert counts["matrix"]["counterfeit"]["likely_genuine"] == 1
    assert counts["matrix"]["counterfeit"]["manual_review"] == 1
    assert counts["counterfeit_recall"] == pytest.approx(1 / 3)
    assert counts["false_fraud_rate"] == pytest.approx(0.5)
    assert counts["false_accept_rate"] == pytest.approx(1 / 3)


def test_integration_requires_both_held_out_groups():
    strong = {
        "counterfeit_recall": 0.4,
        "false_fraud_rate": 0.05,
        "false_accept_rate": 0.0,
    }
    weak = {
        "counterfeit_recall": 0.02,
        "false_fraud_rate": 0.05,
        "false_accept_rate": 0.0,
    }
    assert integration_decision(strong, strong, strong)["integrate"] is True
    refused = integration_decision(strong, strong, weak)
    assert refused["integrate"] is False
    assert refused["checks"]["original_recall_at_least_0.10"] is False


def test_prediction_metadata_uses_pixels_and_names_the_model():
    import torch
    from fraud_detection.documents.stamp_cnn import build_model

    torch.manual_seed(0)
    model = build_model(pretrained=False)
    model.eval()
    page = np.asarray(Image.open(DATASET / "images" / "oval_01_gen_000.jpg").convert("RGB"))
    result = predict_image(model, page, low=0.2, high=0.8)
    assert set(result) >= {"score", "decision", "model", "version", "score_is_calibrated_probability"}
    assert 0.0 <= result["score"] <= 1.0
    assert result["decision"] in {"likely_genuine", "suspicious", "manual_review"}
    assert result["model"] == "resnet18"
    assert result["score_is_calibrated_probability"] is False


def test_public_schema_and_verdict_code_do_not_depend_on_the_cnn():
    import fraud_detection.api.app as app
    import fraud_detection.documents.stamp_alignment as alignment

    assert "cnn_score" not in DocumentMark.model_fields
    assert "verdict" in DocumentMark.model_fields
    assert "stamp_cnn" not in inspect.getsource(app)
    assert "stamp_cnn" not in inspect.getsource(alignment)


def test_saved_checkpoint_keeps_the_validation_threshold():
    assert CHECKPOINT.is_file()
    import torch

    payload = torch.load(CHECKPOINT, map_location="cpu", weights_only=False)
    assert payload["version"] == "stamp-cnn-v1"
    assert payload["test_identities_used_for_training_or_thresholds"] is False
    assert payload["score_is_calibrated_probability"] is False
    assert 0.0 <= payload["threshold_low"] <= payload["threshold_high"] <= 1.0
