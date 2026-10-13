"""ResNet-18 stamp baseline. It does not replace the reference verifier.

Images are classified from pixels only. Manifest fields are training targets
or evaluation slices. Filenames, identity names, mutation lists, split names,
and directory paths are not model inputs.

The decision threshold is chosen on validation identities. ``TARGET_FPR`` is
the same 5% genuine-alert budget used by ``stamp_dataset_v3/evaluate.py``.
The score is a softmax output. It is not a calibrated probability.
"""

from __future__ import annotations

import csv
import io
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from fraud_detection.documents.specimens import _grouped_boxes, crop_array, page_gray
from fraud_detection.paths import PACKAGE

DATASET = PACKAGE / "data" / "stamp_dataset_v3" / "dataset"
MANIFEST = DATASET / "manifest.csv"
CHECKPOINT = PACKAGE / "models" / "artifacts" / "stamp_resnet18.pt"

MODEL_NAME = "resnet18"
MODEL_VERSION = "stamp-cnn-v1"
INPUT_SIZE = 224
SEED = 20261012
TARGET_FPR = 0.05
# Go/no-go after one test look. Fixed before that look.
MIN_TEST_RECALL = 0.20
MAX_TEST_FALSE_FRAUD = 0.10
MAX_TEST_FALSE_ACCEPT = 0.05
MIN_SLICE_RECALL = 0.10

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

DECISIONS = ("likely_genuine", "suspicious", "manual_review")


def load_manifest(path: Path | None = None) -> list[dict]:
    with (path or MANIFEST).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def assert_identity_split(rows: list[dict]) -> None:
    seen: dict[str, set[str]] = {}
    for row in rows:
        seen.setdefault(row["identity_id"], set()).add(row["split"])
    overlap = sorted(identity for identity, splits in seen.items() if len(splits) != 1)
    if overlap:
        raise ValueError(f"identity appears in more than one split: {overlap}")


def label_of(kind: str) -> int:
    """1 is counterfeit. Genuine and harmless recaptures share the other class."""
    return 1 if kind == "counterfeit" else 0


def crop_stamp(page: np.ndarray, pad: int = 8) -> np.ndarray:
    """Largest dark-ink group, padded. The same function is used on every split.

    New v3 files are 566×400 page snippets. The four original identities are
    already tight crops, at four different sizes, and none of them is in the
    training split. Taking the largest ink group presents the stamp in both
    layouts. A miss falls back to the whole image. This does not change labels
    and it does not special-case the test files.
    """
    rgb = page if page.ndim == 3 else np.stack([page, page, page], axis=-1)
    rgb = np.ascontiguousarray(rgb[:, :, :3])
    gray = page_gray(rgb)
    paper = float(np.percentile(gray, 92))
    level = min(paper - 18.0, 210.0)
    if level < 40:
        return rgb
    boxes = _grouped_boxes(gray < level, 30)
    if not boxes:
        return rgb
    box = max(boxes, key=lambda item: item["area"])
    return np.ascontiguousarray(crop_array(rgb, box, pad=pad))


def letterbox(image: Image.Image, size: int = INPUT_SIZE) -> Image.Image:
    """Fit the crop inside a square without stretching it."""
    image = image.convert("RGB")
    width, height = image.size
    scale = size / max(width, height)
    resized = image.resize(
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        Image.Resampling.BILINEAR,
    )
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    canvas.paste(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return canvas


def _jpeg(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def augment_pil(image: Image.Image, rng: random.Random) -> Image.Image:
    """Mild capture noise. No flips and no crops that delete the lettering."""
    if rng.random() < 0.5:
        image = _jpeg(image, rng.randint(40, 90))
    angle = rng.uniform(-8.0, 8.0)
    image = image.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=(255, 255, 255))
    image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.85, 1.15))
    image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.85, 1.15))
    if rng.random() < 0.3:
        image = image.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.1, 1.0)))
    return image


def tensor_from_pil(image: Image.Image):
    import torch
    from torchvision.transforms import functional as transforms_functional

    array = transforms_functional.to_tensor(letterbox(image))
    return transforms_functional.normalize(array, IMAGENET_MEAN, IMAGENET_STD)


def thresholds_from_scores(
    genuine_scores: np.ndarray,
    counterfeit_scores: np.ndarray,
    target_fpr: float = TARGET_FPR,
) -> tuple[float, float]:
    """Validation rule shared with ``stamp_dataset_v3/evaluate.py``.

    Suspicious at or above the genuine quantile ``1 - target_fpr``. Accept at
    or below the counterfeit quantile ``target_fpr``, and never above the
    suspicious cutoff. Scores in between are manual review.
    """
    genuine_scores = np.asarray(genuine_scores, dtype=np.float64)
    counterfeit_scores = np.asarray(counterfeit_scores, dtype=np.float64)
    if genuine_scores.size == 0 or counterfeit_scores.size == 0:
        raise ValueError("threshold selection needs both classes")
    high = float(np.quantile(genuine_scores, 1.0 - target_fpr))
    low = float(min(np.quantile(counterfeit_scores, target_fpr), high))
    return high, low


def decide(score: float, low: float, high: float) -> str:
    if score >= high:
        return "suspicious"
    if score <= low:
        return "likely_genuine"
    return "manual_review"


def decision_counts(labels: np.ndarray, scores: np.ndarray, low: float, high: float) -> dict:
    labels = np.asarray(labels, dtype=np.int32)
    scores = np.asarray(scores, dtype=np.float64)
    decisions = np.array([decide(float(score), low, high) for score in scores])
    matrix = {}
    for label, name in ((0, "genuine"), (1, "counterfeit")):
        chosen = decisions[labels == label]
        matrix[name] = {decision: int(np.sum(chosen == decision)) for decision in DECISIONS}
        matrix[name]["n"] = int(chosen.size)
    genuine_n = matrix["genuine"]["n"]
    counterfeit_n = matrix["counterfeit"]["n"]
    true_positive = matrix["counterfeit"]["suspicious"]
    false_positive = matrix["genuine"]["suspicious"]
    false_accept = matrix["counterfeit"]["likely_genuine"]
    flagged = true_positive + false_positive
    unresolved = int(np.sum(decisions == "manual_review"))
    total = int(labels.size)
    return {
        "matrix": matrix,
        "counterfeit_recall": _rate(true_positive, counterfeit_n),
        "false_fraud_rate": _rate(false_positive, genuine_n),
        "false_accept_rate": _rate(false_accept, counterfeit_n),
        "precision": _rate(true_positive, flagged),
        "unresolved_rate": _rate(unresolved, total),
        "suspicious_count": f"{true_positive}/{flagged}" if flagged else "0/0",
        "recall_count": f"{true_positive}/{counterfeit_n}",
        "false_fraud_count": f"{false_positive}/{genuine_n}",
        "false_accept_count": f"{false_accept}/{counterfeit_n}",
        "unresolved_count": f"{unresolved}/{total}",
    }


def average_precision(labels: np.ndarray, scores: np.ndarray) -> float | None:
    labels = np.asarray(labels, dtype=np.int32)
    scores = np.asarray(scores, dtype=np.float64)
    if labels.size == 0 or len(set(labels.tolist())) < 2:
        return None
    from sklearn.metrics import average_precision_score

    return float(average_precision_score(labels, scores))


def integration_decision(test_counts: dict, synthetic_counts: dict, original_counts: dict) -> dict:
    """Whether the frozen classifier may be attached to the live checker.

    The reference verifier stays the verdict either way. Attachment still
    requires a gain on the generator's held-out identities and on the two
    original held-out identities, so a shortcut that only fits the mutation
    generator does not get into the API.
    """
    checks = {
        "test_recall_at_least_0.20": test_counts["counterfeit_recall"] >= MIN_TEST_RECALL,
        "test_false_fraud_at_most_0.10": test_counts["false_fraud_rate"] <= MAX_TEST_FALSE_FRAUD,
        "test_false_accept_at_most_0.05": test_counts["false_accept_rate"] <= MAX_TEST_FALSE_ACCEPT,
        "new_synthetic_recall_at_least_0.10": synthetic_counts["counterfeit_recall"] >= MIN_SLICE_RECALL,
        "original_recall_at_least_0.10": original_counts["counterfeit_recall"] >= MIN_SLICE_RECALL,
    }
    return {"integrate": all(checks.values()), "checks": checks}


def build_model(pretrained: bool = True):
    import torch
    from torchvision.models import ResNet18_Weights, resnet18

    weights = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
    model = resnet18(weights=weights)
    model.fc = torch.nn.Linear(model.fc.in_features, 2)
    return model


def load_checkpoint(path: Path | None = None, device: str = "cpu") -> tuple[object, dict]:
    import torch

    payload = torch.load(path or CHECKPOINT, map_location=device, weights_only=False)
    model = build_model(pretrained=False)
    model.load_state_dict(payload["state_dict"])
    model.to(device)
    model.eval()
    return model, payload


def iter_prepared(rows: list[dict], seed: int, epoch: int, augment: bool):
    """Yield ``(tensor, label)``. The path is used only to open the file."""
    for index, row in enumerate(rows):
        page = np.asarray(Image.open(DATASET / row["image"]).convert("RGB"), dtype=np.uint8)
        image = Image.fromarray(crop_stamp(page), mode="RGB")
        if augment:
            image = augment_pil(image, random.Random(seed + epoch * 1_000_003 + index))
        yield tensor_from_pil(image), label_of(row["kind"])


def score_rows(model, rows: list[dict], device: str = "cpu", batch_size: int = 32) -> tuple[np.ndarray, np.ndarray]:
    import torch

    labels = np.array([label_of(row["kind"]) for row in rows], dtype=np.int32)
    scores = np.empty(len(rows), dtype=np.float64)
    model.eval()
    for start in range(0, len(rows), batch_size):
        batch_rows = rows[start : start + batch_size]
        tensors = []
        for row in batch_rows:
            page = np.asarray(Image.open(DATASET / row["image"]).convert("RGB"), dtype=np.uint8)
            tensors.append(tensor_from_pil(Image.fromarray(crop_stamp(page), mode="RGB")))
        batch = torch.stack(tensors).to(device)
        with torch.inference_mode():
            probabilities = torch.softmax(model(batch), dim=1)[:, 1]
        scores[start : start + len(batch_rows)] = probabilities.detach().cpu().numpy()
    return labels, scores


def predict_batch(model, images: np.ndarray, device: str = "cpu") -> np.ndarray:
    """``images`` is a batch of RGB uint8 arrays. Returns P(counterfeit-like)."""
    import torch

    tensors = [tensor_from_pil(Image.fromarray(crop_stamp(image), mode="RGB")) for image in images]
    batch = torch.stack(tensors).to(device)
    with torch.inference_mode():
        logits = model(batch)
        probabilities = torch.softmax(logits, dim=1)[:, 1]
    return probabilities.detach().cpu().numpy().astype(np.float64)


def predict_image(model, image: np.ndarray, low: float, high: float, device: str = "cpu") -> dict:
    score = float(predict_batch(model, np.expand_dims(image, 0), device=device)[0])
    return {
        "score": score,
        "decision": decide(score, low, high),
        "model": MODEL_NAME,
        "version": MODEL_VERSION,
        "threshold_low": low,
        "threshold_high": high,
        "score_is_calibrated_probability": False,
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator
