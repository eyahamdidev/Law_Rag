"""Compare decision policies on the labeled pages and score a pre-registered sample.

The pre-registered sample is drawn from filenames only, with seed 20261012,
before any verdict is read. Two reference pages and two counterfeit pages are
taken from each of the four families. That is a reproducible slice, not an
identity-held-out test: every page still comes from the four source documents.

Run:

    .venv/bin/python -m fraud_detection.evaluation.stamp_approaches
"""

from __future__ import annotations

import json
import random
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from fraud_detection.evaluation.stamp_classification import _pdf_page
from fraud_detection.evaluation.stamp_stress import PDF_BY_DOC
from fraud_detection.documents.specimens import SpecimenStore
from fraud_detection.paths import EVAL, STAMP_DATASET

SEED = 20261012
CLASSIFICATION = EVAL / "stamp_classification_results.json"
OUT = EVAL / "stamp_approaches.json"
VERDICTS = ("genuine", "fraudulent", "uncertain", "unrecognized", "missing")


def _confusion(rows: list[dict], predicted_key: str) -> dict:
    matrix = {}
    for ground in ("reference", "counterfeit"):
        subset = [row for row in rows if row["ground_truth"] == ground]
        counts = Counter((row.get(predicted_key) or "missing") for row in subset)
        matrix[ground] = {name: int(counts.get(name, 0)) for name in VERDICTS}
        matrix[ground]["n"] = len(subset)
    return matrix


def _policy_model_binary(row: dict) -> str:
    probability = row.get("genuine_probability")
    if probability is None:
        return "uncertain"
    return "genuine" if float(probability) >= 0.30 else "fraudulent"


def _policy_model_abstain(row: dict) -> str:
    probability = row.get("genuine_probability")
    if probability is None:
        return "uncertain"
    if float(probability) >= 0.45:
        return "genuine"
    if float(probability) < 0.08:
        return "fraudulent"
    return "uncertain"


def _policy_ncc(row: dict) -> str:
    ncc = row.get("alignment_ncc")
    if ncc is None:
        return "missing"
    if float(ncc) >= 0.955:
        return "genuine"
    if float(ncc) < 0.50:
        return "unrecognized"
    return "uncertain"


def _policy_low_ncc_as_fraud(row: dict) -> str:
    """The rejected rule: a low score is treated as fraud."""
    ncc = row.get("alignment_ncc")
    if ncc is None:
        return "missing"
    if float(ncc) >= 0.955:
        return "genuine"
    if float(ncc) < 0.72:
        return "fraudulent"
    return "uncertain"


def _select(seed: int) -> list[dict]:
    rng = random.Random(seed)
    chosen = []
    for doc in PDF_BY_DOC:
        names = sorted(path.name for path in (STAMP_DATASET / doc / "pages").glob("*.jpg"))
        reference = [name for name in names if name.endswith("_reference.jpg")]
        counterfeit = [name for name in names if "counterfeit" in name]
        for name in rng.sample(reference, 2) + rng.sample(counterfeit, 2):
            ground = "reference" if name.endswith("_reference.jpg") else "counterfeit"
            chosen.append({"doc": doc, "name": name, "ground_truth": ground})
    return chosen


def _score_selected(chosen: list[dict]) -> list[dict]:
    root = Path(tempfile.mkdtemp(prefix="stamp-prereg-"))
    stores = {}
    for doc in PDF_BY_DOC:
        store = SpecimenStore(root / doc)
        enrolled = store.enroll(doc, "stamp", _pdf_page(doc), comment=doc)
        if not enrolled.get("enrolled"):
            raise RuntimeError(f"could not enroll {doc}")
        stores[doc] = store
    scored = []
    for item in chosen:
        page = np.asarray(Image.open(STAMP_DATASET / item["doc"] / "pages" / item["name"]).convert("RGB"))
        stamp = stores[item["doc"]].check(item["doc"], page, expect_signature=False)["matches"]["stamp"]
        scored.append(
            {
                **item,
                "verdict": stamp.get("verdict"),
                "reason_codes": stamp.get("reason_codes") or [],
                "alignment_ncc": stamp.get("alignment_ncc"),
                "genuine_probability": stamp.get("genuine_probability"),
                "evidence": stamp.get("evidence") or {},
            }
        )
    return scored


def main() -> None:
    payload = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    rows = payload["rows"]
    policies = (
        (_policy_model_binary, "A_lightgbm_binary_0.30"),
        (_policy_model_abstain, "A_lightgbm_abstain"),
        (_policy_ncc, "B_alignment_ncc_only"),
        (_policy_low_ncc_as_fraud, "B_low_ncc_called_fraud"),
    )
    for policy, name in policies:
        for item in rows:
            item[name] = policy(item)
    chosen = _select(SEED)
    scored = _score_selected(chosen)
    report = {
        "seed": SEED,
        "dataset": "generated scan copies and mutations of four fictitious stamps",
        "labels_csv_present": False,
        "real_world_counterfeits": False,
        "limitation": (
            "Four source documents. Filename holdout and this sample both reuse those identities. "
            "These rates are not a real-world false-acceptance rate."
        ),
        "same_identity_enrolled_pdf": {
            "C_reference_rules": _confusion(rows, "verdict"),
            "A_lightgbm_binary_0.30": _confusion(rows, "A_lightgbm_binary_0.30"),
            "A_lightgbm_abstain": _confusion(rows, "A_lightgbm_abstain"),
            "B_alignment_ncc_only": _confusion(rows, "B_alignment_ncc_only"),
            "B_low_ncc_called_fraud": _confusion(rows, "B_low_ncc_called_fraud"),
        },
        "preregistered": {
            "procedure": (
                "Seed 20261012. For each family, sorted filenames, two reference and two "
                "counterfeit names drawn with random.sample before scoring."
            ),
            "confusion": _confusion(scored, "verdict"),
            "rows": scored,
        },
        "not_added": [
            "YOLO and a learned embedding were not added. Four identities cannot support that evaluation.",
            "LightGBM remains loaded so genuine_probability can be inspected. stamp_verdict ignores it.",
        ],
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report["same_identity_enrolled_pdf"][key] for key in report["same_identity_enrolled_pdf"]}, indent=2))
    print("preregistered", report["preregistered"]["confusion"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
