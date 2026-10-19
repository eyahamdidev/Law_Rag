"""Failure breakdown for the reference stamp verifier.

Re-scores the existing checker. It does not change a threshold, a verdict
rule, or a model. Train and validation identities are the exploratory
comparison. Test identities stay a holdout.

    .venv/bin/python -m fraud_detection.evaluation.stamp_failure_analysis
"""

from __future__ import annotations

import csv
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from fraud_detection.documents.specimens import (
    SpecimenStore,
    _color_mask,
    _grouped_boxes,
    crop_array,
    find_marks,
    page_gray,
)
from fraud_detection.documents.stamp_alignment import crop_quality
from fraud_detection.documents.stamp_cnn import crop_stamp
from fraud_detection.evaluation.stamp_classification import _pdf_page
from fraud_detection.paths import EVAL, PACKAGE

DATASET = PACKAGE / "data" / "stamp_dataset_v3" / "dataset"
MANIFEST = DATASET / "manifest.csv"
OUT = EVAL / "stamp_failure_analysis.json"
PDF_FOR = {"orig_balance": "balance", "orig_labellisation": "labellisation", "orig_capital": "capital", "orig_subvention": "subvention"}
VERDICTS = ("genuine", "fraudulent", "uncertain", "unrecognized", "missing")


def _load() -> list[dict]:
    with MANIFEST.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _image(row: dict) -> np.ndarray:
    return np.asarray(Image.open(DATASET / row["image"]).convert("RGB"), dtype=np.uint8)


def _iou(left: dict, right: dict) -> float:
    x0 = max(left["min_x"], right["min_x"])
    y0 = max(left["min_y"], right["min_y"])
    x1 = min(left["max_x"], right["max_x"])
    y1 = min(left["max_y"], right["max_y"])
    inter = max(0, x1 - x0 + 1) * max(0, y1 - y0 + 1)
    union = left["width"] * left["height"] + right["width"] * right["height"] - inter
    return inter / union if union else 0.0


def _metrics(box: dict, height: int, width: int) -> dict:
    return {
        "width": box["width"],
        "height": box["height"],
        "area": box["area"],
        "aspect": box["width"] / max(1, box["height"]),
        "area_ratio": box["area"] / max(1, height * width),
        "width_ratio": box["width"] / max(1, width),
        "height_frac": box["height"] / max(1, height),
    }


def _gray_fails(metrics: dict) -> list[str]:
    fails = []
    if not (0.70 <= metrics["aspect"] <= 2.25):
        fails.append("aspect")
    if not (0.12 <= metrics["width_ratio"] <= 0.72):
        fails.append("width_ratio")
    if not (0.05 <= metrics["height_frac"] <= 0.55):
        fails.append("height_frac")
    if not (0.0008 <= metrics["area_ratio"] <= 0.05):
        fails.append("area_ratio")
    return fails


def _color_fails(metrics: dict, touches_edge: bool) -> list[str]:
    fails = []
    min_width = 0.06 if touches_edge else 0.10
    if not (0.40 <= metrics["aspect"] <= 2.8):
        fails.append("aspect")
    if metrics["width_ratio"] < min_width:
        fails.append("width_ratio")
    if metrics["height_frac"] < 0.06:
        fails.append("height_frac")
    if not (0.0008 <= metrics["area_ratio"] <= 0.22):
        fails.append("area_ratio")
    return fails


def _plausible(metrics: dict) -> bool:
    return metrics["area_ratio"] >= 0.008 and 0.45 <= metrics["aspect"] <= 4.5 and metrics["height_frac"] >= 0.08


def diagnose(page: np.ndarray) -> dict:
    """Why find_marks did or did not return a stamp. Gates are the live ones."""
    chosen = find_marks(page)["stamp"]
    gray = page_gray(page)
    height, width = gray.shape
    paper = float(np.percentile(gray, 92))
    level = min(paper - 18.0, 210.0)
    gray_boxes = _grouped_boxes(gray < level, 30) if level >= 40 else []
    color = _color_mask(page, 20)
    color_boxes = _grouped_boxes(color, 40) if color is not None and color.any() else []
    chroma_frac = float(color.mean()) if color is not None else 0.0
    pool = [(box, "gray") for box in gray_boxes] + [(box, "color") for box in color_boxes]
    largest = max(pool, key=lambda item: item[0]["area"]) if pool else None
    largest_metrics = _metrics(largest[0], height, width) if largest else None
    gray_fail = _gray_fails(largest_metrics) if largest and largest[1] == "gray" and largest_metrics else []
    if largest and largest[1] == "color" and largest_metrics:
        box = largest[0]
        touches = box["min_x"] <= 2 or box["min_y"] <= 2 or box["max_x"] >= width - 3 or box["max_y"] >= height - 3
        gray_fail = _color_fails(largest_metrics, touches)
    if chosen is None:
        if largest is None or not _plausible(largest_metrics):
            kind = "no_plausible_region"
        else:
            kind = "outside_bounds"
        wrong = False
    else:
        kind = "localized"
        wrong = False
        if largest and largest_metrics and _plausible(largest_metrics):
            if largest[0]["area"] >= 1.5 * chosen["area"] and _iou(chosen, largest[0]) < 0.5:
                wrong = True
                kind = "wrong_region"
    return {
        "class": kind,
        "wrong_region": wrong,
        "chroma20_frac": round(chroma_frac, 4),
        "largest_source": None if largest is None else largest[1],
        "largest": None if largest_metrics is None else {key: round(float(value), 4) for key, value in largest_metrics.items()},
        "largest_failed_gates": gray_fail,
        "chosen_area": None if chosen is None else int(chosen["area"]),
    }


def _enroll(store: SpecimenStore, identity: str, rows: list[dict]) -> bool:
    if identity in PDF_FOR:
        result = store.enroll(identity, "stamp", _pdf_page(PDF_FOR[identity]), comment=identity)
    else:
        reference = next(row for row in rows if row["id"].endswith("_gen_000"))
        result = store.enroll(identity, "stamp", _image(reference), comment=identity)
    return bool(result.get("enrolled"))


def _verdict(stamp: dict) -> str:
    verdict = stamp.get("verdict")
    if verdict:
        return str(verdict)
    if stamp.get("status") == "missing":
        return "missing"
    return "unscored"


def _num(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _score_one(store: SpecimenStore, row: dict) -> dict:
    page = _image(row)
    located = find_marks(page)["stamp"] is not None
    diagnosis = diagnose(page) if row["split"] == "test" or not located else {"class": "localized" if located else "skipped"}
    if row["split"] != "test" and located:
        diagnosis = diagnose(page)
    stamp = store.check(row["identity_id"], page, expect_signature=False)["matches"]["stamp"]
    evidence = dict(stamp.get("evidence") or {})
    evidence.pop("block_map", None)
    crop = None
    region = find_marks(page)["stamp"]
    if region is not None:
        crop = crop_array(page, region)
    return {
        "id": row["id"],
        "identity_id": row["identity_id"],
        "family": row["family"],
        "split": row["split"],
        "source": row["source_dataset"],
        "kind": row["kind"],
        "query": not row["id"].endswith("_gen_000"),
        "verdict": _verdict(stamp),
        "reason_codes": list(stamp.get("reason_codes") or []),
        "localized": located,
        "diagnosis": diagnosis["class"],
        "failed_gates": diagnosis.get("largest_failed_gates") or [],
        "chroma20_frac": diagnosis.get("chroma20_frac"),
        "content": evidence.get("content"),
        "quality": evidence.get("quality"),
        "ncc": _num(evidence.get("ncc")),
        "local_min": _num(evidence.get("local_min")),
        "row_corr": _num(evidence.get("row_corr")),
        "row_floor": _num(evidence.get("row_floor")),
        "mae": _num(evidence.get("mae")),
        "low_block": _num(evidence.get("low_block")),
        "bright_peak": _num(evidence.get("bright_peak")),
        "dark_peak": _num(evidence.get("dark_peak")),
        "crop_side": None if crop is None else int(min(crop.shape[:2])),
        "crop_quality": None if crop is None else crop_quality(crop),
        "jpeg_q": int(row["jpeg_q"]) if row.get("jpeg_q") else None,
    }


def _tally(rows: list[dict]) -> dict:
    labels = ("genuine", "counterfeit")
    matrix = {label: {verdict: 0 for verdict in (*VERDICTS, "unscored")} for label in labels}
    reasons = Counter()
    localized = Counter()
    diagnosis = Counter()
    missing_diagnosis = Counter()
    gates = Counter()
    for row in rows:
        label = "counterfeit" if row["kind"] == "counterfeit" else "genuine"
        matrix[label][row["verdict"]] += 1
        localized[label] += int(row["localized"])
        if row["verdict"] in {"missing", "uncertain", "unrecognized"}:
            reasons[tuple(row["reason_codes"]) or ("(none)",)] += 1
        diagnosis[row["diagnosis"]] += 1
        if row["verdict"] == "missing":
            missing_diagnosis[row["diagnosis"]] += 1
            if row["diagnosis"] == "outside_bounds":
                gates[tuple(row["failed_gates"]) or ("(none)",)] += 1
    counts = {label: sum(matrix[label].values()) for label in labels}
    return {
        "n": len(rows),
        "genuine_n": counts["genuine"],
        "counterfeit_n": counts["counterfeit"],
        "matrix": matrix,
        "localized_genuine": f"{localized['genuine']}/{counts['genuine']}",
        "localized_counterfeit": f"{localized['counterfeit']}/{counts['counterfeit']}",
        "abstain_reason_codes": {",".join(key): value for key, value in reasons.most_common()},
        "localization_class": dict(diagnosis),
        "missing_diagnosis": dict(missing_diagnosis),
        "outside_bounds_gates": {",".join(key): value for key, value in gates.most_common()},
    }


def _group(rows: list[dict], key: str) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[row[key]].append(row)
    return {name: _tally(buckets[name]) for name in sorted(buckets)}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(np.median(np.array(values, dtype=np.float64)))


def _alignment_summary(rows: list[dict]) -> dict:
    fields = ("ncc", "local_min", "row_corr", "mae", "low_block", "bright_peak", "dark_peak")
    out = {}
    for label in ("genuine", "counterfeit"):
        chosen = [row for row in rows if (row["kind"] == "counterfeit") == (label == "counterfeit") and row["ncc"] is not None]
        out[label] = {"n": len(chosen)}
        for field in fields:
            out[label][field] = _median([row[field] for row in chosen if row[field] is not None])
        gaps = [
            row["row_corr"] - row["row_floor"]
            for row in chosen
            if row["row_corr"] is not None and row["row_floor"] is not None
        ]
        out[label]["row_gap"] = _median(gaps)
        out[label]["content"] = dict(Counter(row["content"] for row in chosen))
    return out


def _feature_rows(rows: list[dict]) -> list[dict]:
    ready = []
    for row in rows:
        if not row["query"] or row["ncc"] is None or row["kind"] == "genuine":
            # Clean references are exact copies of the enrolled crop. Harmless
            # recaptures are the genuine class for this comparison.
            if row["kind"] == "genuine":
                continue
        if row["ncc"] is None or not row["query"]:
            continue
        ready.append(row)
    return ready


def _auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    if len(set(labels.tolist())) < 2 or labels.size < 8:
        return None
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(labels, scores))


def _identity_aucs(rows: list[dict]) -> dict:
    """Median within-identity AUC. Higher means the feature ranks counterfeits first."""
    specs = {
        "lower_ncc": lambda row: -row["ncc"],
        "lower_local_min": lambda row: -row["local_min"] if row["local_min"] is not None else None,
        "lower_row_corr": lambda row: -row["row_corr"] if row["row_corr"] is not None else None,
        "lower_row_gap": (
            lambda row: -(row["row_corr"] - row["row_floor"])
            if row["row_corr"] is not None and row["row_floor"] is not None
            else None
        ),
        "higher_mae": lambda row: row["mae"],
        "higher_low_block": lambda row: row["low_block"],
        "higher_bright_peak": lambda row: row["bright_peak"],
        "higher_dark_peak": lambda row: row["dark_peak"],
    }
    by_identity: dict[str, list[dict]] = defaultdict(list)
    for row in _feature_rows(rows):
        by_identity[row["identity_id"]].append(row)
    per_feature: dict[str, list[float]] = {name: [] for name in specs}
    used = []
    for identity, items in sorted(by_identity.items()):
        labels = np.array([1 if row["kind"] == "counterfeit" else 0 for row in items])
        if labels.sum() < 5 or (labels == 0).sum() < 5:
            continue
        used.append(identity)
        for name, getter in specs.items():
            scores = []
            keep = []
            for row, label in zip(items, labels):
                value = getter(row)
                if value is None:
                    continue
                scores.append(value)
                keep.append(label)
            score = _auc(np.array(keep), np.array(scores, dtype=np.float64))
            if score is not None:
                per_feature[name].append(score)
    return {
        "identities": used,
        "median_auc": {name: _median(values) for name, values in per_feature.items()},
        "per_identity_auc": {
            name: {identity: None for identity in used} for name in specs
        },
    }


def _fill_per_identity(rows: list[dict], summary: dict) -> dict:
    specs = summary["median_auc"]
    # Recompute per identity so the report can show the spread. Same rule as above.
    by_identity: dict[str, list[dict]] = defaultdict(list)
    for row in _feature_rows(rows):
        by_identity[row["identity_id"]].append(row)
    getters = {
        "lower_ncc": lambda row: -row["ncc"],
        "lower_local_min": lambda row: -row["local_min"] if row["local_min"] is not None else None,
        "lower_row_corr": lambda row: -row["row_corr"] if row["row_corr"] is not None else None,
        "lower_row_gap": (
            lambda row: -(row["row_corr"] - row["row_floor"])
            if row["row_corr"] is not None and row["row_floor"] is not None
            else None
        ),
        "higher_mae": lambda row: row["mae"],
        "higher_low_block": lambda row: row["low_block"],
        "higher_bright_peak": lambda row: row["bright_peak"],
        "higher_dark_peak": lambda row: row["dark_peak"],
    }
    table = {}
    for identity in summary["identities"]:
        items = by_identity[identity]
        labels = np.array([1 if row["kind"] == "counterfeit" else 0 for row in items])
        table[identity] = {}
        for name, getter in getters.items():
            scores = []
            keep = []
            for row, label in zip(items, labels):
                value = getter(row)
                if value is None:
                    continue
                scores.append(value)
                keep.append(label)
            table[identity][name] = _auc(np.array(keep), np.array(scores, dtype=np.float64))
    summary["per_identity_auc"] = table
    summary["feature_names"] = list(specs)
    return summary


def _rule_overlap(rows: list[dict]) -> dict:
    """How often the live fraud and genuine conjunctions are true. No new cutoff."""
    same = [row for row in rows if row["query"] and row["ncc"] is not None and row["content"] == "same"]
    fraud_band = []
    genuine_band = []
    for row in same:
        row_gap_ok = (
            row["row_corr"] is not None
            and row["row_floor"] is not None
            and row["row_corr"] < row["row_floor"]
        )
        local = row["local_min"] if row["local_min"] is not None else -1
        if row_gap_ok and 0.30 <= row["ncc"] < 0.82 and local >= -0.18:
            fraud_band.append(row)
        close = (
            row["row_corr"] is not None
            and row["row_corr"] >= 0.97
            and row["ncc"] >= 0.955
            and local >= 0.50
            and row["mae"] is not None
            and row["mae"] <= 8
            and (row["low_block"] is None or row["low_block"] <= 0.02)
        )
        if close or (row["ncc"] >= 0.992 and local >= 0.90):
            genuine_band.append(row)
    def _kinds(chosen: list[dict]) -> dict:
        return dict(Counter("counterfeit" if row["kind"] == "counterfeit" else "genuine" for row in chosen))
    return {
        "localized_same_wording": len(same),
        "fraud_conjunction": _kinds(fraud_band),
        "genuine_conjunction": _kinds(genuine_band),
    }


def _pdf_guard() -> dict:
    from fraud_detection.documents.intake import load_pages
    import base64
    from fraud_detection.paths import GENUINE

    names = {
        "balance": "attestation_solde_bancaire.pdf",
        "capital": "attestation_liberation_capital.pdf",
        "labellisation": "attestation_labellisation_startup.pdf",
        "subvention": "decision_attribution_subvention.pdf",
    }
    report = {}
    for doc, filename in names.items():
        raw = (GENUINE / filename).read_bytes()
        _source, pages, _excerpt = load_pages(None, base64.b64encode(raw).decode("ascii"))
        page = pages[0]
        gray_page = np.asarray(Image.fromarray(page).convert("L").convert("RGB"))
        entry = {}
        for label, image in (("color", page), ("grayscale", gray_page)):
            chosen = find_marks(image)["stamp"]
            height, width = image.shape[:2]
            gray = page_gray(image)
            paper = float(np.percentile(gray, 92))
            level = min(paper - 18.0, 210.0)
            boxes = _grouped_boxes(gray < level, 30)
            ranked = sorted(boxes, key=lambda box: box["area"], reverse=True)
            top = []
            for box in ranked[:3]:
                metrics = _metrics(box, height, width)
                top.append({**{key: round(float(value), 4) for key, value in metrics.items()}, "fails": _gray_fails(metrics)})
            entry[label] = {
                "chosen_width_ratio": None if chosen is None else round(chosen["width"] / width, 4),
                "chosen_min_y_frac": None if chosen is None else round(chosen["min_y"] / height, 4),
                "largest_gray_boxes": top,
            }
        report[doc] = entry
    return report


def _cnn_balance() -> dict:
    scores = {row["id"]: float(row["score"]) for row in csv.DictReader((EVAL / "stamp_cnn_test_scores.csv").open())}
    manifest = [row for row in _load() if row["split"] == "test" and not row["id"].endswith("_gen_000")]
    by_identity: dict[str, list[dict]] = defaultdict(list)
    for row in manifest:
        page = _image(row)
        crop = crop_stamp(page)
        corners = np.concatenate(
            [
                page[:8, :8].reshape(-1, 3),
                page[:8, -8:].reshape(-1, 3),
                page[-8:, :8].reshape(-1, 3),
                page[-8:, -8:].reshape(-1, 3),
            ]
        )
        by_identity[row["identity_id"]].append(
            {
                "kind": row["kind"],
                "score": scores[row["id"]],
                "jpeg_q": int(row["jpeg_q"]),
                "file_bytes": (DATASET / row["image"]).stat().st_size,
                "page_w": int(page.shape[1]),
                "page_h": int(page.shape[0]),
                "crop_w": int(crop.shape[1]),
                "crop_h": int(crop.shape[0]),
                "corner_mean": float(corners.mean()),
            }
        )
    summary = {}
    for identity, items in sorted(by_identity.items()):
        summary[identity] = {}
        for label, pred in (("genuine", lambda item: item["kind"] != "counterfeit"), ("counterfeit", lambda item: item["kind"] == "counterfeit")):
            chosen = [item for item in items if pred(item)]
            summary[identity][label] = {
                "n": len(chosen),
                "score_median": _median([item["score"] for item in chosen]),
                "score_p10": float(np.quantile([item["score"] for item in chosen], 0.10)),
                "score_p90": float(np.quantile([item["score"] for item in chosen], 0.90)),
                "jpeg_median": _median([item["jpeg_q"] for item in chosen]),
                "file_bytes_median": _median([item["file_bytes"] for item in chosen]),
                "page_size": f"{chosen[0]['page_w']}x{chosen[0]['page_h']}" if chosen else None,
                "crop_w_median": _median([item["crop_w"] for item in chosen]),
                "crop_h_median": _median([item["crop_h"] for item in chosen]),
                "corner_mean": _median([item["corner_mean"] for item in chosen]),
            }
    return summary


def main() -> None:
    rows = _load()
    by_id: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_id[row["identity_id"]].append(row)
    store = SpecimenStore(Path(tempfile.mkdtemp(prefix="stamp-failure-")))
    records = []
    for identity in sorted(by_id):
        enrolled = _enroll(store, identity, by_id[identity])
        print(identity, "enrolled", enrolled, flush=True)
        if not enrolled:
            continue
        for index, row in enumerate(by_id[identity], start=1):
            records.append(_score_one(store, row))
            if index % 20 == 0:
                print(f"  {identity} {index}/{len(by_id[identity])}", flush=True)
    test = [row for row in records if row["split"] == "test" and row["query"]]
    train = [row for row in records if row["split"] == "train"]
    val = [row for row in records if row["split"] == "val" and row["query"]]
    train_auc = _fill_per_identity(train, _identity_aucs(train))
    val_auc = _fill_per_identity(val, _identity_aucs(val))
    test_auc = _fill_per_identity(test, _identity_aucs(test))
    payload = {
        "thresholds_changed": False,
        "models_trained": False,
        "test_queries": _tally(test),
        "test_by_family": _group(test, "family"),
        "test_by_identity": _group(test, "identity_id"),
        "test_alignment": _alignment_summary(test),
        "test_alignment_by_identity": {name: _alignment_summary(items) for name, items in _group_rows(test).items()},
        "test_rule_overlap": _rule_overlap(test),
        "train_alignment": _alignment_summary([row for row in train if row["query"]]),
        "val_alignment": _alignment_summary(val),
        "train_rule_overlap": _rule_overlap(train),
        "val_rule_overlap": _rule_overlap(val),
        "feature_auc_train_within_identity": train_auc,
        "feature_auc_val_within_identity": val_auc,
        "feature_auc_test_holdout_not_used_to_choose": test_auc,
        "pdf_body_text_guard": _pdf_guard(),
        "cnn_test_identity_cues": _cnn_balance(),
    }
    OUT.write_text(json.dumps(payload, indent=2))
    tally = payload["test_queries"]
    print("test", tally["matrix"], "missing", tally["missing_diagnosis"], flush=True)
    print("wrote", OUT, flush=True)


def _group_rows(rows: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[row["identity_id"]].append(row)
    return buckets


if __name__ == "__main__":
    main()
