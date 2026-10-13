"""Train the supervised stamp verifier on labeled genuine and counterfeit crops.

Every pair has a label: 1 when the later crop is the same stamp, 0 when it is
a counterfeit or a different stamp. Nothing is written into the enrollment
store. That store stays empty until a user enrolls their own genuine stamp.
"""

from __future__ import annotations

import io
import json
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from fraud_detection.documents.stamp_verifier import StampVerifier, pair_features, prepare_stamp
from fraud_detection.evaluation.metrics import classification_report
from fraud_detection.paths import EVAL, STAMP_DATASET, STAMP_VERIFIER


def _held_out(name: str) -> bool:
    return zlib.crc32(name.encode("utf-8")) % 5 == 0


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def dataset_records(root: Path | None = None) -> list[dict]:
    base = root or STAMP_DATASET
    records: list[dict] = []
    if not base.exists():
        return records
    for doc_dir in sorted(path for path in base.iterdir() if path.is_dir()):
        crop_dir = doc_dir / "stamp_crops"
        if not crop_dir.exists():
            continue
        for path in sorted(crop_dir.glob("*.jpg")):
            if path.stem.endswith("_reference"):
                label = "reference"
            elif "counterfeit" in path.stem:
                label = "counterfeit"
            else:
                continue
            records.append(
                {
                    "doc": doc_dir.name,
                    "label": label,
                    "name": path.name,
                    "path": path,
                    "held_out": _held_out(path.name),
                }
            )
    return records


def _jpeg(image: Image.Image, quality: int) -> np.ndarray:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return np.asarray(Image.open(buffer).convert("RGB"), dtype=np.uint8)


def _synthetic_mark(family: int, mutation: str, rng: np.random.Generator) -> np.ndarray:
    canvas = Image.new("RGB", (300, 300), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    color = (25, 78, 176) if family % 2 == 0 else (128, 42, 158)
    stroke = 8 if mutation == "thicker" else 4
    scale = 1.18 if mutation == "bigger" else 1.0
    box = 40 / scale
    far = 260 * scale
    far = min(280, far)
    box = max(16, box)
    if family % 4 == 0:
        draw.ellipse((box, box, far, far), outline=color, width=stroke)
        if mutation != "drop_inner":
            draw.ellipse((box + 36, box + 36, far - 36, far - 36), outline=color, width=max(2, stroke - 2))
        draw.line((110, 150, 190, 150), fill=color, width=max(2, stroke - 2))
    elif family % 4 == 1:
        draw.ellipse((box, box + 30, far, far - 30), outline=color, width=stroke)
        draw.arc((box + 20, box + 50, far - 20, far - 50), 200, 340, fill=color, width=max(2, stroke - 1))
    elif family % 4 == 2:
        draw.rectangle((box, box, far, far), outline=color, width=stroke)
        if mutation != "drop_inner":
            draw.rectangle((box + 16, box + 16, far - 16, far - 16), outline=color, width=max(2, stroke - 2))
    else:
        draw.ellipse((box, box, far, far), outline=color, width=stroke)
        for line in range(4):
            y = 100 + line * 28
            shift = 18 if mutation == "spacing" else 0
            draw.line((90, y, 200 + shift, y + (6 if mutation == "spacing" else 0)), fill=color, width=3)
    if mutation == "rotate":
        canvas = canvas.rotate(5, resample=Image.Resampling.BILINEAR, fillcolor=(255, 255, 255))
    array = np.asarray(canvas, dtype=np.uint8)
    if mutation == "noise":
        noise = rng.integers(-18, 19, size=array.shape, dtype=np.int16)
        array = np.clip(array.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    if mutation == "jpeg":
        array = _jpeg(Image.fromarray(array, mode="RGB"), 45)
    if mutation == "brighter":
        array = np.clip(array.astype(np.int16) + 25, 0, 255).astype(np.uint8)
    return array


def _sample(items: list, count: int, rng: np.random.Generator) -> list:
    if not items:
        return []
    if len(items) <= count:
        return list(items)
    picked = rng.choice(len(items), size=count, replace=False)
    return [items[int(index)] for index in picked]


def _pairs_for_split(records: list[dict], prepared: dict[str, object], held_out: bool, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    features: list[np.ndarray] = []
    labels: list[int] = []
    by_doc: dict[str, dict[str, list]] = {}
    for record in records:
        if bool(record["held_out"]) != held_out:
            continue
        if record["name"] not in prepared:
            continue
        by_doc.setdefault(record["doc"], {"reference": [], "counterfeit": []})[record["label"]].append(record)

    def add(left: str, right: str, label: int) -> None:
        features.append(pair_features(prepared[left], prepared[right]))
        labels.append(label)

    for doc, groups in by_doc.items():
        refs = groups["reference"]
        fakes = groups["counterfeit"]
        other_refs = [record for other, payload in by_doc.items() if other != doc for record in payload["reference"]]
        for anchor in refs:
            for other in _sample([item for item in refs if item["name"] != anchor["name"]], 6, rng):
                add(anchor["name"], other["name"], 1)
            add(anchor["name"], anchor["name"], 1)
            for fake in _sample(fakes, 8, rng):
                add(anchor["name"], fake["name"], 0)
            for foreign in _sample(other_refs, 2, rng):
                add(anchor["name"], foreign["name"], 0)
    if not features:
        return np.empty((0, 0), dtype=np.float32), np.empty((0,), dtype=np.int32)
    return np.vstack(features).astype(np.float32), np.asarray(labels, dtype=np.int32)


def _synthetic_pairs(rng: np.random.Generator, families: range, mutations_positive: tuple[str, ...], mutations_negative: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    features: list[np.ndarray] = []
    labels: list[int] = []
    cache: dict[tuple[int, str], object] = {}

    def prepared(family: int, mutation: str):
        key = (family, mutation)
        if key not in cache:
            cache[key] = prepare_stamp(_synthetic_mark(family, mutation, rng))
        return cache[key]

    for family in families:
        original = prepared(family, "clean")
        if original is None:
            continue
        for mutation in mutations_positive:
            other = prepared(family, mutation)
            if other is None:
                continue
            features.append(pair_features(original, other))
            labels.append(1)
        for mutation in mutations_negative:
            other = prepared(family, mutation)
            if other is None:
                continue
            features.append(pair_features(original, other))
            labels.append(0)
        other_family = prepared((family + 1) % 4 + (family // 4) * 4, "clean")
        if other_family is not None:
            features.append(pair_features(original, other_family))
            labels.append(0)
    if not features:
        return np.empty((0, 0), dtype=np.float32), np.empty((0,), dtype=np.int32)
    return np.vstack(features).astype(np.float32), np.asarray(labels, dtype=np.int32)


def _choose_threshold(probabilities: np.ndarray, labels: np.ndarray) -> float:
    if len(probabilities) == 0:
        return 0.5
    best_threshold = 0.5
    best_score = -1.0
    for threshold in np.linspace(0.15, 0.85, 29):
        genuine = probabilities >= threshold
        true_genuine = labels == 1
        true_fake = labels == 0
        genuine_recall = float((genuine & true_genuine).sum() / max(1, true_genuine.sum()))
        fake_recall = float((~genuine & true_fake).sum() / max(1, true_fake.sum()))
        if genuine_recall < 0.90:
            continue
        score = fake_recall + 0.15 * genuine_recall
        if score > best_score:
            best_score = score
            best_threshold = float(threshold)
    if best_score < 0:
        for threshold in np.linspace(0.15, 0.85, 29):
            genuine = probabilities >= threshold
            accuracy = float((genuine == (labels == 1)).mean())
            if accuracy > best_score:
                best_score = accuracy
                best_threshold = float(threshold)
    return best_threshold


def _round(value) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return round(number, 4)


def _rates(probabilities: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    if len(labels) == 0:
        return {"pairs": 0}
    genuine = probabilities >= threshold
    true_genuine = labels == 1
    true_fake = labels == 0
    report = classification_report(labels.tolist(), probabilities.tolist(), threshold=threshold, top_k=min(50, len(labels)))
    return {
        "pairs": int(len(labels)),
        "genuine_pairs": int(true_genuine.sum()),
        "fake_pairs": int(true_fake.sum()),
        "genuine_recall": _round(float((genuine & true_genuine).sum() / max(1, true_genuine.sum()))),
        "fake_recall": _round(float((~genuine & true_fake).sum() / max(1, true_fake.sum()))),
        "pr_auc": _round(report["pr_auc"]),
        "precision": _round(report["precision"]),
        "recall": _round(report["recall"]),
    }


def _probabilities(model: StampVerifier, features: np.ndarray) -> np.ndarray:
    if len(features) == 0:
        return np.empty((0,), dtype=np.float32)
    return model.model.predict_proba(features)[:, 1]


def train(dataset: Path | None = None, out: Path | None = None) -> dict:
    rng = np.random.default_rng(0)
    records = dataset_records(dataset)
    prepared = {}
    for record in records:
        stamp = prepare_stamp(_load_rgb(record["path"]))
        if stamp is not None:
            prepared[record["name"]] = stamp
    train_x, train_y = _pairs_for_split(records, prepared, held_out=False, rng=rng)
    val_x, val_y = _pairs_for_split(records, prepared, held_out=True, rng=rng)
    synthetic_x, synthetic_y = _synthetic_pairs(
        rng,
        range(16),
        ("clean", "noise", "rotate", "jpeg", "brighter"),
        ("bigger", "thicker", "drop_inner", "spacing"),
    )
    if len(train_x) and len(synthetic_x):
        train_x = np.vstack([train_x, synthetic_x])
        train_y = np.concatenate([train_y, synthetic_y])
    elif len(synthetic_x):
        train_x, train_y = synthetic_x, synthetic_y
    probe = StampVerifier().fit(train_x, train_y, threshold=0.5)
    val_prob = _probabilities(probe, val_x)
    threshold = _choose_threshold(val_prob, val_y)
    probe.threshold = threshold
    validation = _rates(val_prob, val_y, threshold)
    train_rates = _rates(_probabilities(probe, train_x), train_y, threshold)

    left_out = []
    docs = sorted({record["doc"] for record in records})
    for doc in docs:
        kept = [record for record in records if record["doc"] != doc and not record["held_out"]]
        held = [record for record in records if record["doc"] == doc]
        fit_x, fit_y = _pairs_for_split(kept, prepared, held_out=False, rng=rng)
        # _pairs_for_split filters on held_out flag. Rebuild held pairs directly.
        held_features, held_labels = _document_pairs(held, prepared, rng)
        if len(fit_x) == 0 or len(held_features) == 0:
            continue
        if len(synthetic_x):
            fit_x = np.vstack([fit_x, synthetic_x])
            fit_y = np.concatenate([fit_y, synthetic_y])
        fold = StampVerifier().fit(fit_x, fit_y, threshold=threshold)
        fold_rates = _rates(_probabilities(fold, held_features), held_labels, threshold)
        fold_rates["doc"] = doc
        left_out.append(fold_rates)

    probe.save(out or STAMP_VERIFIER)
    metrics = {
        "method": "supervised",
        "unsupervised_used": False,
        "task": "Compare one later stamp crop with the single genuine crop a user enrolled.",
        "backend": probe.backend,
        "threshold": threshold,
        "feature_count": int(train_x.shape[1]),
        "train_pairs": int(len(train_y)),
        "dataset_crops": len(records),
        "enrollment_store": "empty_until_a_user_enrolls",
        "train": train_rates,
        "validation": validation,
        "leave_one_document_out": left_out,
    }
    EVAL.mkdir(parents=True, exist_ok=True)
    (EVAL / "stamp_verifier_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def _document_pairs(records: list[dict], prepared: dict, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    features: list[np.ndarray] = []
    labels: list[int] = []
    refs = [record for record in records if record["label"] == "reference" and record["name"] in prepared]
    fakes = [record for record in records if record["label"] == "counterfeit" and record["name"] in prepared]
    for anchor in refs:
        for other in _sample([item for item in refs if item["name"] != anchor["name"]], 4, rng):
            features.append(pair_features(prepared[anchor["name"]], prepared[other["name"]]))
            labels.append(1)
        for fake in _sample(fakes, 6, rng):
            features.append(pair_features(prepared[anchor["name"]], prepared[fake["name"]]))
            labels.append(0)
    if not features:
        return np.empty((0, 0), dtype=np.float32), np.empty((0,), dtype=np.int32)
    return np.vstack(features).astype(np.float32), np.asarray(labels, dtype=np.int32)


def main() -> None:
    metrics = train()
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
