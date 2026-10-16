"""Record why labeled counterfeits stay uncertain.

Each family is enrolled from its genuine PDF. Every labeled page is checked
with the live store. The script does not change thresholds. It writes the
measurements the verdict already computed, plus the gap between the text-line
score and that stamp's harmless-recapture floor.

Run:

    .venv/bin/python -m fraud_detection.evaluation.stamp_unresolved
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from fraud_detection.documents.specimens import SpecimenStore
from fraud_detection.evaluation.stamp_classification import _label, _pdf_page
from fraud_detection.evaluation.stamp_stress import PDF_BY_DOC
from fraud_detection.paths import EVAL, STAMP_DATASET

OUT = EVAL / "stamp_unresolved.json"


def _summarize(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    def at(q: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return round(ordered[index], 4)
    return {"n": len(ordered), "min": at(0), "p10": at(0.1), "p50": at(0.5), "p90": at(0.9), "max": at(1)}


def _row(doc: str, name: str, ground: str, stamp: dict, *, note: str = "") -> dict:
    evidence = stamp.get("evidence") or {}
    row_corr = evidence.get("row_corr")
    row_floor = evidence.get("row_floor")
    gap = None
    if row_corr is not None and row_floor is not None:
        gap = round(float(row_corr) - float(row_floor), 4)
    return {
        "doc": doc,
        "name": name,
        "ground_truth": ground,
        "note": note,
        "verdict": stamp.get("verdict"),
        "reason_codes": stamp.get("reason_codes") or [],
        "alignment_ncc": stamp.get("alignment_ncc"),
        "row_corr": row_corr,
        "row_floor": row_floor,
        "row_gap": gap,
        "low_block": evidence.get("low_block"),
        "worst_block": evidence.get("worst_block"),
        "mae": evidence.get("mae"),
        "local_min": evidence.get("local_min"),
        "quality": evidence.get("quality"),
        "content": evidence.get("content"),
        "bright_peak": evidence.get("bright_peak"),
        "dark_peak": evidence.get("dark_peak"),
    }


def _recaptures(page: np.ndarray) -> list[tuple[str, np.ndarray]]:
    image = Image.fromarray(page)
    jpeg = Image.fromarray(page)
    buffer_path = None
    import io
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=60)
    buffer.seek(0)
    jpeg = Image.open(buffer).convert("RGB")
    return [
        ("rotate_2", np.asarray(image.rotate(2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255)))),
        ("rotate_12", np.asarray(image.rotate(12, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255)))),
        ("blur_1.2", np.asarray(image.filter(ImageFilter.GaussianBlur(1.2)))),
        ("jpeg_60", np.asarray(jpeg)),
        ("grayscale", np.asarray(image.convert("L").convert("RGB"))),
    ]


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="stamp-unresolved-"))
    rows: list[dict] = []
    for doc in PDF_BY_DOC:
        print(doc, flush=True)
        store = SpecimenStore(root / doc)
        page = _pdf_page(doc)
        enrolled = store.enroll(doc, "stamp", page, comment=doc)
        if not enrolled.get("enrolled"):
            raise RuntimeError(enrolled)
        for label, edited in _recaptures(page):
            stamp = store.check(doc, edited, expect_signature=False)["matches"]["stamp"]
            rows.append(_row(doc, label, "recapture", stamp, note=label))
            print(" ", label, stamp.get("verdict"), stamp.get("reason_codes"), flush=True)
        for path in sorted((STAMP_DATASET / doc / "pages").glob("*.jpg")):
            query = np.asarray(Image.open(path).convert("RGB"))
            stamp = store.check(doc, query, expect_signature=False)["matches"]["stamp"]
            rows.append(_row(doc, path.name, _label(path.name), stamp))
    groups = {
        "reference": [row for row in rows if row["ground_truth"] == "reference"],
        "counterfeit_fraudulent": [row for row in rows if row["ground_truth"] == "counterfeit" and row["verdict"] == "fraudulent"],
        "counterfeit_uncertain": [row for row in rows if row["ground_truth"] == "counterfeit" and row["verdict"] == "uncertain"],
        "recapture": [row for row in rows if row["ground_truth"] == "recapture"],
    }
    summary = {}
    for name, subset in groups.items():
        summary[name] = {
            "n": len(subset),
            "verdicts": dict(Counter(row["verdict"] for row in subset)),
            "reasons": dict(Counter(",".join(row["reason_codes"]) for row in subset)),
            "content": dict(Counter(row["content"] for row in subset)),
            "row_gap": _summarize([row["row_gap"] for row in subset if row["row_gap"] is not None]),
            "worst_block": _summarize([float(row["worst_block"]) for row in subset if row["worst_block"] is not None]),
            "low_block": _summarize([float(row["low_block"]) for row in subset if row["low_block"] is not None]),
            "ncc": _summarize([float(row["alignment_ncc"]) for row in subset if row["alignment_ncc"] is not None]),
            "mae": _summarize([float(row["mae"]) for row in subset if row["mae"] is not None]),
        }
        print(name, summary[name]["n"], summary[name]["reasons"], flush=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
