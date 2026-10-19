"""Audit stamp dataset v3 and score two systems without touching test labels.

The classifier is the existing pair model (``StampVerifier``). One copy is the
frozen model shipped with the repo. Another is fit only on the train
identities. Thresholds for both come from the validation identities, using the
same quantile rule as ``stamp_dataset_v3/evaluate.py``. The test identities
are scored after that and are not used to move a threshold.

The stamp agent is the live reference checker. It enrolls the clean genuine
image for a new identity, or the genuine PDF for an original identity, and
then uses the decision rules already in the service. Those rules are not
refit here.

Run:

    .venv/bin/python -m fraud_detection.evaluation.stamp_v3_audit
"""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from fraud_detection.documents.specimens import SpecimenStore, find_marks
from fraud_detection.documents.stamp_verifier import StampVerifier, pair_features, prepare_stamp
from fraud_detection.evaluation.stamp_classification import _pdf_page
from fraud_detection.paths import EVAL, PACKAGE, STAMP_VERIFIER

ROOT = PACKAGE / "data" / "stamp_dataset_v3"
DATASET = ROOT / "dataset"
MANIFEST = DATASET / "manifest.csv"
OUT = EVAL / "stamp_v3_audit.json"
TARGET_FPR = 0.05


def _load_manifest() -> list[dict]:
    with MANIFEST.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _image(row: dict) -> np.ndarray:
    return np.asarray(Image.open(DATASET / row["image"]).convert("RGB"), dtype=np.uint8)


def _kind_group(kind: str) -> str:
    return "counterfeit" if kind == "counterfeit" else "genuine"


def _quantile_thresholds(rows: list[dict], scores: dict[str, float]) -> dict:
    """Same rule as stamp_dataset_v3/evaluate.py. Validation rows only."""
    val = [row for row in rows if row["split"] == "val" and row["id"] in scores]
    genuine = np.array([scores[row["id"]] for row in val if row["kind"] != "counterfeit"], dtype=np.float64)
    fake = np.array([scores[row["id"]] for row in val if row["kind"] == "counterfeit"], dtype=np.float64)
    high = float(np.quantile(genuine, 1 - TARGET_FPR))
    low = min(float(np.quantile(fake, TARGET_FPR)), high)
    return {
        "target_fpr": TARGET_FPR,
        "val_genuine": int(len(genuine)),
        "val_counterfeit": int(len(fake)),
        "fraud_if_score_at_least": high,
        "accept_if_score_at_most": low,
        "rule": "flag fraud if P(counterfeit) >= high; accept if P(counterfeit) <= low; otherwise uncertain",
    }


def _band(score: float, thresholds: dict) -> str:
    if score >= thresholds["fraud_if_score_at_least"]:
        return "fraudulent"
    if score <= thresholds["accept_if_score_at_most"]:
        return "genuine"
    return "uncertain"


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _classifier_metrics(rows: list[dict], scores: dict[str, float], thresholds: dict) -> dict:
    labels = ("genuine", "counterfeit")
    verdicts = ("genuine", "fraudulent", "uncertain")
    matrix = {label: {verdict: 0 for verdict in verdicts} for label in labels}
    used = [row for row in rows if row["id"] in scores]
    for row in used:
        matrix[_kind_group(row["kind"])][_band(scores[row["id"]], thresholds)] += 1
    genuine_n = sum(matrix["genuine"].values())
    fake_n = sum(matrix["counterfeit"].values())
    false_fraud = matrix["genuine"]["fraudulent"]
    detected = matrix["counterfeit"]["fraudulent"]
    false_accept = matrix["counterfeit"]["genuine"]
    uncertain = matrix["genuine"]["uncertain"] + matrix["counterfeit"]["uncertain"]
    precision = _safe_rate(detected, detected + false_fraud)
    return {
        "n": len(used),
        "n_genuine": genuine_n,
        "n_counterfeit": fake_n,
        "confusion": matrix,
        "counterfeit_precision": precision,
        "counterfeit_precision_count": f"{detected}/{detected + false_fraud}",
        "counterfeit_recall": _safe_rate(detected, fake_n),
        "counterfeit_recall_count": f"{detected}/{fake_n}",
        "false_fraud_rate": _safe_rate(false_fraud, genuine_n),
        "false_fraud_count": f"{false_fraud}/{genuine_n}",
        "false_accept_rate": _safe_rate(false_accept, fake_n),
        "false_accept_count": f"{false_accept}/{fake_n}",
        "uncertain_rate": _safe_rate(uncertain, len(used)),
        "uncertain_count": f"{uncertain}/{len(used)}",
        "unrecognized_rate": None,
        "unrecognized_reason": "This classifier has no unrecognized verdict. A low score is genuine or uncertain, not an unknown identity.",
    }


def _group_metrics(rows: list[dict], scores: dict[str, float], thresholds: dict, key: str) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["id"] in scores:
            grouped[str(row[key])].append(row)
    return {name: _classifier_metrics(grouped[name], scores, thresholds) for name in sorted(grouped)}


def _agent_metrics(records: list[dict]) -> dict:
    labels = ("genuine", "counterfeit")
    verdicts = ("genuine", "fraudulent", "uncertain", "unrecognized", "missing", "unscored")
    matrix = {label: {verdict: 0 for verdict in verdicts} for label in labels}
    for record in records:
        pred = record["verdict"] if record["verdict"] in verdicts else "unscored"
        matrix[_kind_group(record["kind"])][pred] += 1
    genuine_n = sum(matrix["genuine"].values())
    fake_n = sum(matrix["counterfeit"].values())
    false_fraud = matrix["genuine"]["fraudulent"]
    detected = matrix["counterfeit"]["fraudulent"]
    false_accept = matrix["counterfeit"]["genuine"]
    uncertain = matrix["genuine"]["uncertain"] + matrix["counterfeit"]["uncertain"]
    unrecognized = matrix["genuine"]["unrecognized"] + matrix["counterfeit"]["unrecognized"]
    missing = matrix["genuine"]["missing"] + matrix["counterfeit"]["missing"]
    unscored = matrix["genuine"]["unscored"] + matrix["counterfeit"]["unscored"]
    total = len(records)
    return {
        "n": total,
        "n_genuine": genuine_n,
        "n_counterfeit": fake_n,
        "confusion": matrix,
        "counterfeit_precision": _safe_rate(detected, detected + false_fraud),
        "counterfeit_precision_count": f"{detected}/{detected + false_fraud}" if detected + false_fraud else "undefined",
        "counterfeit_precision_reason": None if detected + false_fraud else "No fraudulent verdict was issued, so precision has no denominator.",
        "counterfeit_recall": _safe_rate(detected, fake_n),
        "counterfeit_recall_count": f"{detected}/{fake_n}",
        "false_fraud_rate": _safe_rate(false_fraud, genuine_n),
        "false_fraud_count": f"{false_fraud}/{genuine_n}",
        "false_accept_rate": _safe_rate(false_accept, fake_n),
        "false_accept_count": f"{false_accept}/{fake_n}",
        "uncertain_rate": _safe_rate(uncertain, total),
        "uncertain_count": f"{uncertain}/{total}",
        "unrecognized_rate": _safe_rate(unrecognized, total),
        "unrecognized_count": f"{unrecognized}/{total}",
        "missing_rate": _safe_rate(missing, total),
        "missing_count": f"{missing}/{total}",
        "unscored_rate": _safe_rate(unscored, total),
        "unscored_count": f"{unscored}/{total}",
        "unscored_reason": "The clean reference image had no stamp region the agent could enroll, so later images of that identity were not compared.",
    }


def _audit(rows: list[dict]) -> dict:
    splits_by_id: dict[str, set[str]] = defaultdict(set)
    orgs: dict[str, set[str]] = defaultdict(set)
    missing_files = []
    hashes: dict[str, list[str]] = defaultdict(list)
    jpeg = defaultdict(list)
    sizes = Counter()
    kinds = Counter()
    by_split_kind = Counter()
    by_id = {}
    mutations = Counter()
    bad_mutations = []
    parent_mismatch = []
    for row in rows:
        splits_by_id[row["identity_id"]].add(row["split"])
        orgs[row["organization"]].add(row["identity_id"])
        kinds[row["kind"]] += 1
        by_split_kind[(row["split"], row["kind"])] += 1
        path = DATASET / row["image"]
        if not path.is_file():
            missing_files.append(row["image"])
            continue
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        hashes[digest].append(row["id"])
        with Image.open(path) as image:
            sizes[f"{image.size[0]}x{image.size[1]}"] += 1
        jpeg[(row["source_dataset"], row["kind"])].append(int(float(row["jpeg_q"])))
        slot = by_id.setdefault(
            row["identity_id"],
            {
                "family": row["family"],
                "split": row["split"],
                "source": row["source_dataset"],
                "organization": row["organization"],
                "kinds": Counter(),
            },
        )
        slot["kinds"][row["kind"]] += 1
        if row["kind"] == "counterfeit":
            try:
                parsed = json.loads(row["mutations"])
            except json.JSONDecodeError:
                bad_mutations.append(row["id"])
                parsed = []
            if row["source_dataset"] == "v3" and not parsed:
                bad_mutations.append(row["id"])
            for item in parsed:
                mutations[str(item).split(":")[0]] += 1
        parent = row["parent_reference"]
        if row["source_dataset"] == "v3" and not str(parent).startswith(row["identity_id"]):
            parent_mismatch.append(row["id"])
    leaked = {key: sorted(value) for key, value in splits_by_id.items() if len(value) > 1}
    shared_orgs = {org: sorted(ids) for org, ids in orgs.items() if len(ids) > 1}
    duplicate_images = {digest: ids for digest, ids in hashes.items() if len(ids) > 1}
    identity_rows = []
    split_counts = Counter()
    family_split = Counter()
    for identity, payload in sorted(by_id.items()):
        split_counts[payload["split"]] += 1
        family_split[(payload["family"], payload["split"])] += 1
        identity_rows.append(
            {
                "identity_id": identity,
                "family": payload["family"],
                "split": payload["split"],
                "source": payload["source"],
                "organization": payload["organization"],
                "kinds": dict(payload["kinds"]),
            }
        )
    return {
        "rows": len(rows),
        "identity_count": len(by_id),
        "missing_files": missing_files,
        "identities_in_multiple_splits": leaked,
        "organizations_shared_by_identities": shared_orgs,
        "duplicate_image_hashes": len(duplicate_images),
        "parent_reference_outside_identity": parent_mismatch,
        "bad_counterfeit_mutations": bad_mutations[:20],
        "bad_counterfeit_mutation_count": len(bad_mutations),
        "kind_counts": dict(kinds),
        "split_kind_counts": {f"{split}|{kind}": count for (split, kind), count in sorted(by_split_kind.items())},
        "identities_per_split": dict(split_counts),
        "identities_per_family_split": {f"{family}|{split}": count for (family, split), count in sorted(family_split.items())},
        "image_sizes": dict(sizes),
        "jpeg_q_by_source_kind": {
            f"{source}|{kind}": {
                "n": len(values),
                "min": min(values),
                "median": int(np.median(values)),
                "max": max(values),
            }
            for (source, kind), values in sorted(jpeg.items())
        },
        "v3_counterfeit_mutation_types": dict(mutations),
        "identities": identity_rows,
        "filename_encodes_label": True,
        "filename_note": "New files use _gen_, _har_, and _cfr_. Original files use _reference and _counterfeit. The filename alone identifies the class. The models below do not read it.",
    }


def _separation(rows: list[dict], prepared: dict[str, object]) -> dict:
    """How easily a non-stamp cue separates genuine variants from counterfeits.

    Measured on the whole manifest as a property of the files. It is not a
    threshold and it is not used for the reported decisions.
    """
    groups = {"genuine_variant": [], "counterfeit": [], "genuine": []}
    for row in rows:
        stamp = prepared.get(row["id"])
        if stamp is None:
            continue
        path = DATASET / row["image"]
        image = _image(row)
        gray = image.mean(axis=2)
        # Top band is the page phrase, above a centered stamp.
        top = float(gray[:50].mean())
        sharp = float(np.abs(np.diff(gray.astype(np.float32), axis=0)).mean())
        groups[row["kind"]].append(
            {
                "width_ratio_vs_self_box": stamp.width,
                "file_bytes": path.stat().st_size,
                "top_mean": top,
                "sharpness": sharp,
                "jpeg_q": int(float(row["jpeg_q"])),
            }
        )

    def auc(kind_a: str, kind_b: str, field: str) -> float | None:
        left = [item[field] for item in groups[kind_a]]
        right = [item[field] for item in groups[kind_b]]
        if not left or not right:
            return None
        # Rank AUC of field for distinguishing b from a. 0.5 means no separation.
        scores = np.array(left + right, dtype=np.float64)
        labels = np.array([0] * len(left) + [1] * len(right))
        order = np.argsort(scores)
        ranks = np.empty(len(scores), dtype=np.float64)
        ranks[order] = np.arange(1, len(scores) + 1)
        positives = ranks[labels == 1]
        return round(float((positives.sum() - len(right) * (len(right) + 1) / 2) / (len(left) * len(right))), 4)

    summary = {}
    for field in ("file_bytes", "top_mean", "sharpness", "jpeg_q", "width_ratio_vs_self_box"):
        summary[field] = {
            "auc_counterfeit_vs_genuine_variant": auc("genuine_variant", "counterfeit", field),
            "genuine_variant_median": round(float(np.median([item[field] for item in groups["genuine_variant"]])), 2),
            "counterfeit_median": round(float(np.median([item[field] for item in groups["counterfeit"]])), 2),
            "clean_genuine_median": round(float(np.median([item[field] for item in groups["genuine"]])), 2) if groups["genuine"] else None,
        }
    summary["prepared"] = {kind: len(items) for kind, items in groups.items()}
    return summary


def _reference_id(identity: str, rows: list[dict]) -> str | None:
    for row in rows:
        if row["identity_id"] == identity and row["id"].endswith("_gen_000"):
            return row["id"]
    return None


def _scores_against_reference(rows: list[dict], prepared: dict[str, object], model: StampVerifier) -> dict[str, float]:
    by_id: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_id[row["identity_id"]].append(row)
    scores: dict[str, float] = {}
    for identity, items in by_id.items():
        reference_key = _reference_id(identity, items)
        reference = prepared.get(reference_key) if reference_key else None
        if reference is None:
            continue
        for row in items:
            query = prepared.get(row["id"])
            if query is None:
                continue
            probability = float(model.model.predict_proba(pair_features(reference, query).reshape(1, -1))[0, 1])
            scores[row["id"]] = round(1.0 - probability, 6)
    return scores


def _fit_train_model(rows: list[dict], prepared: dict[str, object]) -> StampVerifier:
    features = []
    labels = []
    by_id: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["split"] == "train":
            by_id[row["identity_id"]].append(row)
    for items in by_id.values():
        reference_key = _reference_id(items[0]["identity_id"], items)
        reference = prepared.get(reference_key) if reference_key else None
        if reference is None:
            continue
        for row in items:
            query = prepared.get(row["id"])
            if query is None or row["id"] == reference_key:
                continue
            features.append(pair_features(reference, query))
            labels.append(0 if row["kind"] == "counterfeit" else 1)
    model = StampVerifier().fit(np.vstack(features).astype(np.float32), np.asarray(labels, dtype=np.int32))
    return model


def _write_predictions(path: Path, scores: dict[str, float]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "score"])
        writer.writeheader()
        for key in sorted(scores):
            writer.writerow({"id": key, "score": scores[key]})


def _agent(rows: list[dict]) -> list[dict]:
    test = [row for row in rows if row["split"] == "test"]
    by_id: dict[str, list[dict]] = defaultdict(list)
    for row in test:
        by_id[row["identity_id"]].append(row)
    store = SpecimenStore(Path(tempfile.mkdtemp(prefix="stamp-v3-agent-")))
    records = []
    pdf_for = {"orig_balance": "balance", "orig_labellisation": "labellisation"}
    for identity, items in sorted(by_id.items()):
        if identity in pdf_for:
            enrolled = store.enroll(identity, "stamp", _pdf_page(pdf_for[identity]), comment=identity)
            reference = "genuine pdf"
        else:
            reference_row = next(row for row in items if row["id"].endswith("_gen_000"))
            enrolled = store.enroll(identity, "stamp", _image(reference_row), comment=identity)
            reference = reference_row["id"]
        print(identity, "enrolled", enrolled.get("enrolled"), enrolled.get("reason"), flush=True)
        for index, row in enumerate(items, start=1):
            image = _image(row)
            located = find_marks(image)["stamp"] is not None
            if not enrolled.get("enrolled"):
                verdict = "unscored"
                reasons: list[str] = []
                status = "no_reference"
            else:
                stamp = store.check(identity, image, expect_signature=False)["matches"]["stamp"]
                verdict = stamp.get("verdict") or ("missing" if stamp.get("status") == "missing" else "unscored")
                reasons = list(stamp.get("reason_codes") or [])
                status = stamp.get("status")
            records.append(
                {
                    "id": row["id"],
                    "identity_id": identity,
                    "family": row["family"],
                    "source": row["source_dataset"],
                    "kind": row["kind"],
                    "difficulty": row["difficulty"],
                    "verdict": verdict,
                    "status": status,
                    "reason_codes": reasons,
                    "stamp_localized": located,
                    "reference": reference,
                }
            )
            if index % 25 == 0:
                print(f"  {identity} {index}/{len(items)}", flush=True)
    return records


def main() -> None:
    rows = _load_manifest()
    print("auditing", len(rows), "rows", flush=True)
    audit = _audit(rows)
    print("preparing images", flush=True)
    prepared = {}
    for index, row in enumerate(rows, start=1):
        prepared[row["id"]] = prepare_stamp(_image(row))
        if index % 200 == 0:
            print(f"  prepared {index}/{len(rows)}", flush=True)
    audit["pixel_cues"] = _separation(rows, prepared)
    print("fitting train identities", flush=True)
    trained = _fit_train_model(rows, prepared)
    trained_scores = _scores_against_reference(rows, prepared, trained)
    frozen = StampVerifier.load(STAMP_VERIFIER)
    frozen_scores = _scores_against_reference(rows, prepared, frozen)
    # Original identities have no clean generated reference image. Score them
    # against the stamp cropped from the genuine PDF, which is the reference
    # the agent enrolls. This uses the frozen and the retrained models the
    # same way.
    pdf_crop = {}
    for identity, doc in (("orig_balance", "balance"), ("orig_capital", "capital"), ("orig_labellisation", "labellisation"), ("orig_subvention", "subvention")):
        page = _pdf_page(doc)
        region = find_marks(page)["stamp"]
        if region is None:
            pdf_crop[identity] = None
            continue
        from fraud_detection.documents.specimens import crop_array

        pdf_crop[identity] = prepare_stamp(crop_array(page, region))
    for identity, reference in pdf_crop.items():
        if reference is None:
            continue
        for row in rows:
            if row["identity_id"] != identity:
                continue
            query = prepared.get(row["id"])
            if query is None:
                continue
            for model, sink in ((trained, trained_scores), (frozen, frozen_scores)):
                probability = float(model.model.predict_proba(pair_features(reference, query).reshape(1, -1))[0, 1])
                sink[row["id"]] = round(1.0 - probability, 6)
    trained_thresholds = _quantile_thresholds(rows, trained_scores)
    frozen_thresholds = _quantile_thresholds(rows, frozen_scores)
    pred_trained = EVAL / "stamp_v3_predictions_retrained.csv"
    pred_frozen = EVAL / "stamp_v3_predictions_frozen.csv"
    _write_predictions(pred_trained, trained_scores)
    _write_predictions(pred_frozen, frozen_scores)
    test_rows = [row for row in rows if row["split"] == "test"]
    # Exclude the enrolled clean image from a second view. Comparing it with
    # itself is an exact copy, not a later document.
    test_queries = [row for row in test_rows if not row["id"].endswith("_gen_000")]
    new_test = [row for row in test_queries if row["source_dataset"] == "v3"]
    original_test = [row for row in test_queries if row["source_dataset"] == "v2"]

    def pack(scores: dict[str, float], thresholds: dict) -> dict:
        return {
            "thresholds_from_validation": thresholds,
            "test_including_reference_image": _classifier_metrics(test_rows, scores, thresholds),
            "test_queries": _classifier_metrics(test_queries, scores, thresholds),
            "test_new_identities": _classifier_metrics(new_test, scores, thresholds),
            "test_original_identities": _classifier_metrics(original_test, scores, thresholds),
            "test_by_family": _group_metrics(test_queries, scores, thresholds, "family"),
            "test_by_identity": _group_metrics(test_queries, scores, thresholds, "identity_id"),
            "scores": len(scores),
        }

    print("agent", flush=True)
    agent_rows = _agent(rows)
    agent_new = [row for row in agent_rows if row["source"] == "v3" and not row["id"].endswith("_gen_000")]
    agent_original = [row for row in agent_rows if row["source"] == "v2"]
    agent_queries = [row for row in agent_rows if not row["id"].endswith("_gen_000")]

    def agent_by(records: list[dict], key: str) -> dict:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for record in records:
            grouped[str(record[key])].append(record)
        return {name: _agent_metrics(grouped[name]) for name in sorted(grouped)}

    payload = {
        "commit": "b958666",
        "manifest": str(MANIFEST.relative_to(PACKAGE)),
        "audit": {key: value for key, value in audit.items() if key != "identities"},
        "identity_table": audit["identities"],
        "classifier_retrained_on_train_identities": pack(trained_scores, trained_thresholds),
        "classifier_frozen_production_model": pack(frozen_scores, frozen_thresholds),
        "frozen_model_caveat": "The shipped LightGBM was trained on crops from the four original documents. Scores for orig_balance and orig_labellisation are not identity-held-out for that model. The 18 train identities in v3 were not in that training set. Its weights were not changed. The threshold used here was selected on v3 validation only.",
        "retrained_model_caveat": "Fit only on the 18 train identities, genuine variants against counterfeits of the same identity. The clean reference image was the left side of each pair and was not a training label by itself. Validation selected the accept and fraud cutoffs. Test identities were not used to fit or to move those cutoffs. The production model file was not overwritten.",
        "agent": {
            "test_queries": _agent_metrics(agent_queries),
            "test_new_identities": _agent_metrics(agent_new),
            "test_original_identities": _agent_metrics(agent_original),
            "test_by_family": agent_by(agent_queries, "family"),
            "test_by_identity": agent_by(agent_queries, "identity_id"),
            "records": agent_rows,
        },
        "previous_full_page_baseline": {
            "source": "680-case stress at the same decision rules, full pages, four original PDFs enrolled",
            "reference_pages": {"n": 200, "genuine": 9, "fraudulent": 0, "uncertain": 191},
            "counterfeit_pages": {"n": 200, "genuine": 0, "fraudulent": 13, "uncertain": 187},
            "note": "Those pages are not the v3 crop files. Balance and labellisation full-page counts from that run were 0/50 and 7/50 fraudulent for balance, and 0/50 and 0/50 for labellisation.",
        },
    }
    # Drop per-image agent records from the summary numbers already stored; keep them.
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
