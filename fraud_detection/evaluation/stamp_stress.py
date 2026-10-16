"""Repeatable stress test of the stamp verifier.

The enrollment store is a temporary directory. Nothing under
``fraud_detection/data/specimens`` is read or written.

Ground truth for the labeled pages is the filename suffix
``_reference`` or ``_counterfeit``. The dataset README describes a
``labels.csv`` with difficulty and mutation columns. That file is not
in this checkout, so those columns are not invented.

Run:

    .venv/bin/python -m fraud_detection.evaluation.stamp_stress
"""

from __future__ import annotations

import base64
import csv
import io
import json
import shutil
import tempfile
import traceback
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from fraud_detection.documents.intake import load_pages
from fraud_detection.documents.specimens import SpecimenStore, find_marks
from fraud_detection.paths import GENUINE, STAMP_DATASET

SEED = 11
OUT = Path(__file__).resolve().parent / "stamp_stress_results"

# Dataset README and data/genuine/README.md. One fictitious stamp identity each.
PDF_BY_DOC = {
    "balance": "attestation_solde_bancaire.pdf",
    "capital": "attestation_liberation_capital.pdf",
    "labellisation": "attestation_labellisation_startup.pdf",
    "subvention": "decision_attribution_subvention.pdf",
}

FIELDS = [
    "category",
    "severity",
    "sample_id",
    "source_doc",
    "enrolled_doc",
    "ground_truth",
    "predicted",
    "status",
    "alignment_ncc",
    "genuine_probability",
    "similarity",
    "stamp_detected",
    "crop_w",
    "crop_h",
    "read_text",
    "enrolled_text",
    "review_reason",
    "reason_codes",
    "review_recommended",
    "risk_level",
    "differences",
    "held_out",
    "error",
    "note",
]


def _held_out(name: str) -> bool:
    return zlib.crc32(name.encode("utf-8")) % 5 == 0


def _rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def _pdf_page(doc: str) -> np.ndarray:
    raw = (GENUINE / PDF_BY_DOC[doc]).read_bytes()
    _source, pages, _excerpt = load_pages(None, base64.b64encode(raw).decode("ascii"))
    if not pages:
        raise RuntimeError(f"no page rendered for {doc}")
    return pages[0]


def _label_from_name(name: str) -> str:
    if name.endswith("_reference.jpg") or name.endswith("_reference"):
        return "reference"
    if name.endswith("_counterfeit.jpg") or "counterfeit" in name:
        return "counterfeit"
    return "unlabeled"


def _judge(store: SpecimenStore, entity: str, page: np.ndarray) -> dict:
    located = find_marks(page).get("stamp")
    crop_w = crop_h = None
    if located is not None:
        crop_w = int(located["width"])
        crop_h = int(located["height"])
    try:
        result = store.check(entity, page, expect_signature=False)
    except Exception as exc:
        return {
            "predicted": None,
            "status": "error",
            "alignment_ncc": None,
            "genuine_probability": None,
            "similarity": None,
            "stamp_detected": located is not None,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "read_text": "",
            "enrolled_text": "",
            "review_reason": None,
            "reason_codes": "",
            "review_recommended": None,
            "risk_level": None,
            "differences": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    stamp = result["matches"].get("stamp") or {}
    differences = stamp.get("differences") or []
    return {
        "predicted": stamp.get("verdict"),
        "status": stamp.get("status"),
        "alignment_ncc": stamp.get("alignment_ncc"),
        "genuine_probability": stamp.get("genuine_probability"),
        "similarity": stamp.get("similarity"),
        "stamp_detected": located is not None and stamp.get("status") not in {None, "missing"},
        "crop_w": crop_w,
        "crop_h": crop_h,
        "read_text": stamp.get("read_text") or "",
        "enrolled_text": stamp.get("enrolled_text") or "",
        "review_reason": stamp.get("review_reason"),
        "reason_codes": ",".join(stamp.get("reason_codes") or []),
        "review_recommended": stamp.get("review_recommended"),
        "risk_level": stamp.get("risk_level"),
        "differences": ",".join(differences),
        "error": "",
    }


def _row(category: str, severity: str, sample_id: str, source_doc: str, enrolled_doc: str, ground_truth: str, judged: dict, *, note: str = "") -> dict:
    return {
        "category": category,
        "severity": severity,
        "sample_id": sample_id,
        "source_doc": source_doc,
        "enrolled_doc": enrolled_doc,
        "ground_truth": ground_truth,
        "predicted": judged.get("predicted"),
        "status": judged.get("status"),
        "alignment_ncc": judged.get("alignment_ncc"),
        "genuine_probability": judged.get("genuine_probability"),
        "similarity": judged.get("similarity"),
        "stamp_detected": judged.get("stamp_detected"),
        "crop_w": judged.get("crop_w"),
        "crop_h": judged.get("crop_h"),
        "read_text": (judged.get("read_text") or "")[:180],
        "enrolled_text": (judged.get("enrolled_text") or "")[:180],
        "review_reason": judged.get("review_reason"),
        "reason_codes": judged.get("reason_codes") or "",
        "review_recommended": judged.get("review_recommended"),
        "risk_level": judged.get("risk_level"),
        "differences": judged.get("differences") or "",
        "held_out": _held_out(sample_id),
        "error": judged.get("error") or "",
        "note": note,
    }


def _perspective(image: Image.Image, strength: float) -> Image.Image:
    width, height = image.size
    dx = width * strength
    dy = height * strength
    source = [(0, 0), (width, 0), (width, height), (0, height)]
    target = [(dx, dy * 0.3), (width - dx, 0), (width - dx * 0.4, height), (0, height - dy)]
    matrix = []
    for (sx, sy), (tx, ty) in zip(source, target):
        matrix.append([tx, ty, 1, 0, 0, 0, -sx * tx, -sx * ty])
        matrix.append([0, 0, 0, tx, ty, 1, -sy * tx, -sy * ty])
    coefficients = np.linalg.lstsq(np.asarray(matrix, dtype=np.float64), np.asarray(source, dtype=np.float64).reshape(8), rcond=None)[0]
    return image.transform(image.size, Image.Transform.PERSPECTIVE, coefficients.tolist(), Image.Resampling.BICUBIC, fillcolor=(255, 255, 255))


def _jpeg(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def _noise(image: Image.Image, sigma: float, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    array = np.asarray(image).astype(np.int16)
    array = array + rng.normal(0, sigma, array.shape)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), mode="RGB")


def _page_transforms() -> list[tuple[str, str, object]]:
    """Mild changes should keep a genuine stamp recognizable. Hard changes may degrade it."""
    return [
        ("rot_p2", "mild", lambda im: im.rotate(2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))),
        ("rot_m2", "mild", lambda im: im.rotate(-2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))),
        ("rot_p6", "medium", lambda im: im.rotate(6, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))),
        ("rot_m6", "medium", lambda im: im.rotate(-6, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))),
        ("rot_p12", "hard", lambda im: im.rotate(12, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))),
        ("jpeg_75", "mild", lambda im: _jpeg(im, 75)),
        ("jpeg_45", "medium", lambda im: _jpeg(im, 45)),
        ("jpeg_25", "hard", lambda im: _jpeg(im, 25)),
        ("bright_0.85", "mild", lambda im: ImageEnhance.Brightness(im).enhance(0.85)),
        ("bright_1.10", "mild", lambda im: ImageEnhance.Brightness(im).enhance(1.10)),
        ("bright_0.70", "medium", lambda im: ImageEnhance.Brightness(im).enhance(0.70)),
        ("bright_0.50", "hard", lambda im: ImageEnhance.Brightness(im).enhance(0.50)),
        ("scale_0.85", "mild", lambda im: im.resize((max(8, int(im.width * 0.85)), max(8, int(im.height * 0.85))), Image.Resampling.BICUBIC)),
        ("scale_0.65", "medium", lambda im: im.resize((max(8, int(im.width * 0.65)), max(8, int(im.height * 0.65))), Image.Resampling.BICUBIC)),
        ("blur_0.6", "mild", lambda im: im.filter(ImageFilter.GaussianBlur(0.6))),
        ("blur_1.4", "medium", lambda im: im.filter(ImageFilter.GaussianBlur(1.4))),
        ("blur_2.8", "hard", lambda im: im.filter(ImageFilter.GaussianBlur(2.8))),
        ("contrast_0.85", "mild", lambda im: ImageEnhance.Contrast(im).enhance(0.85)),
        ("color_0.70", "mild", lambda im: ImageEnhance.Color(im).enhance(0.70)),
        ("noise_4", "mild", lambda im: _noise(im, 4, SEED)),
        ("shift_24", "mild", lambda im: im.transform(im.size, Image.Transform.AFFINE, (1, 0, 24, 0, 1, 18), fillcolor=(255, 255, 255))),
        ("gray", "mild", lambda im: im.convert("L").convert("RGB")),
        ("perspective_0.04", "medium", lambda im: _perspective(im, 0.04)),
        ("perspective_0.10", "hard", lambda im: _perspective(im, 0.10)),
    ]


def _edits(crop: Image.Image) -> list[tuple[str, str, Image.Image]]:
    """Single-feature edits. These are controlled stress tests, not real counterfeits."""
    base = crop.convert("RGB")
    array = np.asarray(base).copy()
    height, width = array.shape[:2]
    made: list[tuple[str, str, Image.Image]] = []

    shifted = array.copy()
    y0, y1 = int(height * 0.42), int(height * 0.58)
    shifted[y0:y1] = np.roll(shifted[y0:y1], 8, axis=1)
    made.append(("band_shift_8px", "medium", Image.fromarray(shifted, mode="RGB")))

    patch = array.copy()
    cy, cx = height // 2, width // 2
    patch[cy - 7 : cy + 7, cx - 7 : cx + 7] = 255
    made.append(("occlude_14px", "mild", Image.fromarray(patch, mode="RGB")))
    wider = array.copy()
    wider[cy - 16 : cy + 16, cx - 16 : cx + 16] = 255
    made.append(("occlude_32px", "medium", Image.fromarray(wider, mode="RGB")))

    border = array.copy()
    border[:, max(0, width - 10) :] = 255
    made.append(("erase_right_border", "medium", Image.fromarray(border, mode="RGB")))

    gray = array.mean(axis=2)
    ink = gray < 170
    recolored = array.copy()
    recolored[ink, 0] = np.clip(recolored[ink, 0].astype(np.int16) + 80, 0, 255)
    made.append(("ink_shift_red", "mild", Image.fromarray(recolored, mode="RGB")))

    thick = base.filter(ImageFilter.MinFilter(3))
    made.append(("thicken_min3", "medium", thick))
    made.append(("thicken_and_shift", "hard", Image.fromarray(np.roll(np.asarray(thick), 6, axis=1), mode="RGB")))
    return made


def _paste(crop: Image.Image, *, shift: tuple[int, int] = (80, 90), size: tuple[int, int] = (900, 1200), bg: tuple[int, int, int] = (255, 255, 255)) -> np.ndarray:
    page = Image.new("RGB", size, bg)
    stamp = crop.convert("RGB")
    page.paste(stamp, shift)
    return np.asarray(page)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _subset(rows: list[dict], **equals) -> list[dict]:
    chosen = []
    for row in rows:
        if all(row.get(key) == value for key, value in equals.items()):
            chosen.append(row)
    return chosen


def _metrics(rows: list[dict]) -> dict:
    """Labeled same-family pages only. Uncertain is not counted as a counterfeit detection."""
    references = [row for row in rows if row["ground_truth"] == "reference"]
    counterfeits = [row for row in rows if row["ground_truth"] == "counterfeit"]
    genuine_accept = sum(row["predicted"] == "genuine" for row in references)
    false_reject = sum(row["predicted"] == "fraudulent" for row in references)
    genuine_uncertain = sum(row["predicted"] == "uncertain" for row in references)
    genuine_unrecognized = sum(row["predicted"] == "unrecognized" for row in references)
    genuine_missing = sum(row["predicted"] in {None, ""} or row["status"] in {"missing", "error", "no_specimen"} for row in references)
    false_accept = sum(row["predicted"] == "genuine" for row in counterfeits)
    detected = sum(row["predicted"] == "fraudulent" for row in counterfeits)
    fake_uncertain = sum(row["predicted"] == "uncertain" for row in counterfeits)
    fake_unrecognized = sum(row["predicted"] == "unrecognized" for row in counterfeits)
    true_positive = detected
    false_positive = false_reject
    false_negative = len(counterfeits) - detected
    precision = _rate(true_positive, true_positive + false_positive)
    recall = _rate(true_positive, true_positive + false_negative)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    labels = ("reference", "counterfeit")
    verdicts = ("genuine", "fraudulent", "uncertain", "unrecognized", "other")
    matrix = {label: {verdict: 0 for verdict in verdicts} for label in labels}
    for row in references + counterfeits:
        verdict = row["predicted"] if row["predicted"] in {"genuine", "fraudulent", "uncertain", "unrecognized"} else "other"
        matrix[row["ground_truth"]][verdict] += 1
    detected_pages = sum(bool(row["stamp_detected"]) for row in references + counterfeits)
    ocr_empty = sum(not (row.get("read_text") or "").strip() for row in references + counterfeits if row["stamp_detected"])
    return {
        "n_reference": len(references),
        "n_counterfeit": len(counterfeits),
        "genuine_acceptance_rate": _rate(genuine_accept, len(references)),
        "genuine_accepted": genuine_accept,
        "false_rejection_rate": _rate(false_reject, len(references)),
        "genuine_called_fraudulent": false_reject,
        "genuine_uncertain": genuine_uncertain,
        "genuine_unrecognized": genuine_unrecognized,
        "genuine_not_scored": genuine_missing,
        "counterfeit_false_accept_rate": _rate(false_accept, len(counterfeits)),
        "counterfeit_false_accepts": false_accept,
        "counterfeit_detection_rate": _rate(detected, len(counterfeits)),
        "counterfeit_detected_fraudulent": detected,
        "counterfeit_uncertain": fake_uncertain,
        "counterfeit_unrecognized": fake_unrecognized,
        "precision_fraudulent": precision,
        "recall_fraudulent": recall,
        "f1_fraudulent": f1,
        "confusion": matrix,
        "stamp_detected": detected_pages,
        "stamp_detected_rate": _rate(detected_pages, len(references) + len(counterfeits)),
        "ocr_empty_when_detected": ocr_empty,
        "review_recommended_reference": sum(row.get("review_recommended") is True for row in references),
        "review_rate_reference": _rate(sum(row.get("review_recommended") is True for row in references), len(references)),
        "high_risk_reference": sum(row.get("risk_level") == "high" for row in references),
        "review_recommended_counterfeit": sum(row.get("review_recommended") is True for row in counterfeits),
        "review_rate_counterfeit": _rate(sum(row.get("review_recommended") is True for row in counterfeits), len(counterfeits)),
        "high_risk_counterfeit": sum(row.get("risk_level") == "high" for row in counterfeits),
    }


def _variation_summary(rows: list[dict]) -> dict:
    summary = {}
    for severity in ("mild", "medium", "hard"):
        group = [row for row in rows if row["severity"] == severity]
        summary[severity] = {
            "n": len(group),
            "genuine": sum(row["predicted"] == "genuine" for row in group),
            "uncertain": sum(row["predicted"] == "uncertain" for row in group),
            "fraudulent": sum(row["predicted"] == "fraudulent" for row in group),
            "unrecognized": sum(row["predicted"] == "unrecognized" for row in group),
            "other": sum(row["predicted"] not in {"genuine", "uncertain", "fraudulent", "unrecognized"} for row in group),
        }
    return summary


def _markdown(report: dict) -> str:
    base = report["baseline_same_family"]
    hold = report["baseline_filename_holdout"]
    matrix = base["confusion"]
    lines = [
        "# Stamp stress test",
        "",
        report["limitation"],
        "",
        "## Commands",
        "",
        "```bash",
        ".venv/bin/python -m fraud_detection.evaluation.stamp_stress",
        "```",
        "",
        f"Results directory: `{report['output_dir']}`.",
        f"Cases: {report['n_cases']}. Seed: {SEED}. Enrollment directory was temporary and was deleted.",
        "",
        "## Dataset",
        "",
        report["inventory_note"],
        "",
        "## Baseline, same family",
        "",
        "Each genuine PDF was enrolled for its own company. Every labeled page of that family was then scored. "
        "A counterfeit counted as detected only when the verdict was `fraudulent`. `uncertain` and `unrecognized` are separate.",
        "",
        f"- Reference pages: {base['n_reference']}. Accepted as genuine: {base['genuine_accepted']} ({base['genuine_acceptance_rate']}).",
        f"- Called fraudulent (false rejection): {base['genuine_called_fraudulent']} ({base['false_rejection_rate']}).",
        f"- Reference uncertain: {base['genuine_uncertain']}. Reference unrecognized: {base['genuine_unrecognized']}.",
        f"- Counterfeit pages: {base['n_counterfeit']}. Accepted as genuine: {base['counterfeit_false_accepts']} ({base['counterfeit_false_accept_rate']}).",
        f"- Called fraudulent: {base['counterfeit_detected_fraudulent']} ({base['counterfeit_detection_rate']}).",
        f"- Counterfeit uncertain: {base['counterfeit_uncertain']}. Counterfeit unrecognized: {base['counterfeit_unrecognized']}.",
        f"- Review recommended: {base.get('review_recommended_reference')} / {base['n_reference']} reference pages, {base.get('review_recommended_counterfeit')} / {base['n_counterfeit']} counterfeit pages.",
        f"- High risk tier: {base.get('high_risk_reference')} reference, {base.get('high_risk_counterfeit')} counterfeit. A high tier queues a person. It is not a fraud probability.",
        f"- Precision / recall / F1 for the fraudulent verdict: {base['precision_fraudulent']} / {base['recall_fraudulent']} / {base['f1_fraudulent']}.",
        f"- Stamp detected on labeled pages: {base['stamp_detected']} ({base['stamp_detected_rate']}). OCR empty when a stamp was detected: {base['ocr_empty_when_detected']}.",
        "",
        "Confusion matrix (rows are ground truth, columns are the verdict):",
        "",
        "| Ground truth | genuine | fraudulent | uncertain | unrecognized | other |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label in ("reference", "counterfeit"):
        cell = matrix[label]
        lines.append(
            f"| {label} | {cell['genuine']} | {cell['fraudulent']} | {cell['uncertain']} | {cell['unrecognized']} | {cell['other']} |"
        )
    lines.extend(
        [
            "",
            "The filename holdout (`zlib.crc32(name) % 5 == 0`) is the split used by `train_stamps.py`. "
            "It is not a held-out stamp identity. The model was trained on this same four-document set, so these rates are not an independent trial.",
            "",
            f"- Holdout references accepted as genuine: {hold['genuine_accepted']}/{hold['n_reference']} ({hold['genuine_acceptance_rate']}).",
            f"- Holdout references called fraudulent: {hold['genuine_called_fraudulent']}.",
            f"- Holdout counterfeits accepted as genuine: {hold['counterfeit_false_accepts']}/{hold['n_counterfeit']} ({hold['counterfeit_false_accept_rate']}).",
            f"- Holdout counterfeits called fraudulent: {hold['counterfeit_detected_fraudulent']} ({hold['counterfeit_detection_rate']}).",
            f"- Holdout counterfeits uncertain: {hold['counterfeit_uncertain']}.",
            "",
            "## Genuine variations of the enrolled PDF",
            "",
            "These are synthetic scan changes of the enrolled genuine page. Mild cases are the ones a normal scan should still accept. "
            "A hard blur or a strong perspective warp may legitimately be uncertain. Calling one fraudulent is recorded, and it is a false rejection only when the stamp is still intact.",
            "",
            "| Severity | n | genuine | uncertain | fraudulent | unrecognized | other |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for severity, counts in report["variations"].items():
        lines.append(
            f"| {severity} | {counts['n']} | {counts['genuine']} | {counts['uncertain']} | {counts['fraudulent']} | {counts['unrecognized']} | {counts['other']} |"
        )
    lines.extend(
        [
            "",
            "## Controlled edits",
            "",
            "One feature of the enrolled crop was changed, then pasted on a clean page. These are not real counterfeits. "
            "A genuine verdict here is a false accept of a modified drawing.",
            "",
            f"- n: {report['edits']['n']}. Predicted genuine: {report['edits']['genuine']}. Fraudulent: {report['edits']['fraudulent']}. Uncertain: {report['edits']['uncertain']}. Unrecognized: {report['edits']['unrecognized']}.",
            "",
            "## Other legitimate stamps",
            "",
            "A reference page or genuine PDF from another organization. Expected verdict: unrecognized. Fraudulent is the wrong accusation.",
            "",
            f"- n: {report['foreign']['n']}. Unrecognized: {report['foreign']['unrecognized']}. Uncertain: {report['foreign']['uncertain']}. Genuine: {report['foreign']['genuine']}. Fraudulent: {report['foreign']['fraudulent']}.",
            "",
            "## API workflow",
            "",
        ]
    )
    for item in report["api"]:
        lines.append(f"- {item['name']}: {'pass' if item['passed'] else 'FAIL'} — {item['detail']}")
    lines.extend(["", "## False accepts (counterfeit page called genuine)", ""])
    if report["false_accept_ids"]:
        for item in report["false_accept_ids"]:
            lines.append(
                f"- `{item['sample_id']}` enrolled `{item['enrolled_doc']}` ncc={item['alignment_ncc']} p={item['genuine_probability']} status={item['status']}"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Genuine pages called fraudulent", ""])
    if report["false_reject_ids"]:
        for item in report["false_reject_ids"]:
            lines.append(
                f"- `{item['sample_id']}` ({item['category']}, {item['severity']}) ncc={item['alignment_ncc']} p={item['genuine_probability']}"
            )
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Assessment",
            "",
            report["assessment"],
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _api_workflow(rows: list[dict]) -> list[dict]:
    from fastapi.testclient import TestClient

    from fraud_detection.api.app import create_app
    from fraud_detection.inference.pipeline import FraudDetectionEngine

    root = Path(tempfile.mkdtemp(prefix="stamp-api-"))
    results: list[dict] = []

    def payment(receiver: str) -> dict:
        return {
            "transaction_id": "stress-pay",
            "timestamp": "2024-11-18T11:00:00",
            "amount": 125.0,
            "currency": "EUR",
            "transaction_type": "transfer",
            "sender_id": "fr-sender",
            "receiver_id": receiver,
            "country_from": "FR",
            "country_to": "FR",
        }

    def score(client: TestClient, image: np.ndarray, receiver: str, secret: str | None = None) -> dict:
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        document = {"image_base64": encoded, "expect_signature": False}
        if secret:
            document["tenant_secret"] = secret
        response = client.post(
            "/v1/score",
            json={"transaction": payment(receiver), "document": document},
        )
        return {"status_code": response.status_code, "body": response.json() if response.status_code == 200 else response.text}

    try:
        import os

        os.environ["FRAUD_SPECIMEN_DIR"] = str(root)
        client = TestClient(create_app(FraudDetectionEngine()))
        capital = _pdf_page("capital")
        other = _pdf_page("subvention")
        first = score(client, capital, "company-a")
        stamp = next(item for item in first["body"]["documents"]["marks"] if item["kind"] == "stamp")
        proposal = stamp.get("proposal_id")
        results.append({"name": "enroll_proposal", "passed": stamp.get("status") == "awaiting_approval" and bool(proposal), "detail": stamp.get("status")})
        declined_client = TestClient(create_app(FraudDetectionEngine()))
        # Decline on a fresh store so the approved path below is independent.
        os.environ["FRAUD_SPECIMEN_DIR"] = str(root / "decline")
        (root / "decline").mkdir()
        decline_app = TestClient(create_app(FraudDetectionEngine()))
        proposed = score(decline_app, capital, "company-a")
        decline_stamp = next(item for item in proposed["body"]["documents"]["marks"] if item["kind"] == "stamp")
        declined = decline_app.post("/v1/documents/decide", json={"proposal_id": decline_stamp["proposal_id"], "approve": False})
        saved = list((root / "decline").glob("index.json"))
        results.append({"name": "decline_saves_nothing", "passed": declined.status_code == 200 and declined.json().get("enrolled") is False and not saved, "detail": str(declined.json())})

        os.environ["FRAUD_SPECIMEN_DIR"] = str(root / "approve")
        (root / "approve").mkdir()
        app = TestClient(create_app(FraudDetectionEngine()))
        proposed = score(app, capital, "company-a")
        stamp = next(item for item in proposed["body"]["documents"]["marks"] if item["kind"] == "stamp")
        approved = app.post("/v1/documents/decide", json={"proposal_id": stamp["proposal_id"], "approve": True, "comment": "Stress reference"})
        results.append({"name": "approve_enrolls", "passed": approved.status_code == 200 and approved.json().get("enrolled") is True, "detail": approved.json().get("reason")})
        secret = approved.json().get("tenant_secret")
        again = score(app, capital, "company-a", secret)
        again_stamp = next(item for item in again["body"]["documents"]["marks"] if item["kind"] == "stamp")
        repeat = score(app, capital, "company-a", secret)
        repeat_stamp = next(item for item in repeat["body"]["documents"]["marks"] if item["kind"] == "stamp")
        index = json.loads((root / "approve" / "index.json").read_text(encoding="utf-8"))
        results.append({
            "name": "exact_resubmit_stable",
            "passed": again_stamp.get("verdict") == "genuine" and repeat_stamp.get("verdict") == "genuine" and len(index.get("specimens") or []) == 1,
            "detail": f"{again_stamp.get('verdict')} then {repeat_stamp.get('verdict')}, specimens={len(index.get('specimens') or [])}",
        })
        darker = np.clip(capital.astype(np.float32) * 0.75, 0, 255).astype(np.uint8)
        dark = score(app, darker, "company-a", secret)
        dark_stamp = next(item for item in dark["body"]["documents"]["marks"] if item["kind"] == "stamp")
        results.append({"name": "darker_scan", "passed": dark_stamp.get("verdict") in {"genuine", "uncertain"} and dark_stamp.get("proposal_id") is None, "detail": str(dark_stamp.get("verdict"))})
        foreign = score(app, other, "company-a", secret)
        foreign_stamp = next(item for item in foreign["body"]["documents"]["marks"] if item["kind"] == "stamp")
        results.append({"name": "other_organization", "passed": foreign_stamp.get("verdict") == "unrecognized" and bool(foreign_stamp.get("proposal_id")), "detail": str(foreign_stamp.get("verdict"))})
        other_company = score(app, capital, "company-b")
        other_company_stamp = next(item for item in other_company["body"]["documents"]["marks"] if item["kind"] == "stamp")
        results.append({"name": "company_isolation", "passed": other_company_stamp.get("status") == "awaiting_approval", "detail": str(other_company_stamp.get("status"))})
        restarted = TestClient(create_app(FraudDetectionEngine()))
        persisted = score(restarted, capital, "company-a", secret)
        persisted_stamp = next(item for item in persisted["body"]["documents"]["marks"] if item["kind"] == "stamp")
        results.append({"name": "restart_keeps_reference", "passed": persisted_stamp.get("verdict") == "genuine", "detail": str(persisted_stamp.get("verdict"))})
        unknown = app.post("/v1/documents/decide", json={"proposal_id": "does-not-exist", "approve": True})
        results.append({"name": "unknown_proposal", "passed": unknown.status_code == 200 and unknown.json().get("reason") == "unknown_proposal", "detail": str(unknown.json().get("reason"))})
        bad_kind = app.post("/v1/documents/enroll", json={"entity_id": "company-a", "kind": "logo", "image_base64": "aaaa"})
        results.append({"name": "invalid_kind", "passed": bad_kind.status_code == 200 and bad_kind.json().get("enrolled") is False, "detail": str(bad_kind.json().get("reason"))})
        garbage = app.post(
            "/v1/score",
            json={"transaction": payment("company-a"), "document": {"image_base64": base64.b64encode(b"not-an-image").decode("ascii"), "expect_signature": False}},
        )
        results.append({
            "name": "malformed_image",
            "passed": garbage.status_code == 200 and garbage.json()["documents"]["checked"] is False and "document_unreadable" in garbage.json()["fraud_types"],
            "detail": str(garbage.json().get("fraud_types")),
        })
        bad_pdf = app.post(
            "/v1/score",
            json={"transaction": payment("company-a"), "document": {"pdf_base64": base64.b64encode(b"%PDF-not-really").decode("ascii"), "expect_signature": False}},
        )
        results.append({
            "name": "malformed_pdf",
            "passed": bad_pdf.status_code == 200 and bad_pdf.json()["documents"]["checked"] is False,
            "detail": str(bad_pdf.json().get("fraud_types")),
        })
        blank = np.full((500, 400, 3), 255, np.uint8)
        blank_score = score(app, blank, "company-a", secret)
        blank_stamp = next(item for item in blank_score["body"]["documents"]["marks"] if item["kind"] == "stamp")
        results.append({"name": "blank_page", "passed": blank_stamp.get("status") == "missing" and blank_stamp.get("verdict") != "genuine", "detail": str(blank_stamp.get("status"))})
        rows.append(_row("api", "workflow", "see_summary", "capital", "capital", "workflow", {"predicted": None, "status": "see_summary", "error": ""}, note="api cases are in summary.json"))
    except Exception as exc:
        results.append({"name": "api_suite", "passed": False, "detail": traceback.format_exc(limit=4)})
        rows.append(_row("api", "workflow", "exception", "capital", "capital", "workflow", {"predicted": None, "status": "error", "error": str(exc)}))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return results


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    rows: list[dict] = []
    store_root = Path(tempfile.mkdtemp(prefix="stamp-stress-"))
    store = SpecimenStore(store_root)
    print(f"enrolling genuine PDFs into {store_root}", flush=True)
    enrolled_pages: dict[str, np.ndarray] = {}
    for doc in PDF_BY_DOC:
        try:
            page = _pdf_page(doc)
            enrolled_pages[doc] = page
            saved = store.enroll(doc, "stamp", page, comment=f"Stress reference {doc}")
            print(f"  enroll {doc}: {saved.get('reason')} detected={saved.get('enrolled')}", flush=True)
            if not saved.get("enrolled"):
                rows.append(_row("enroll", "setup", PDF_BY_DOC[doc], doc, doc, "reference", {"predicted": None, "status": "error", "stamp_detected": False, "error": saved.get("reason") or "enroll failed"}))
                continue
            judged = _judge(store, doc, page)
            rows.append(_row("enrolled_pdf", "exact", PDF_BY_DOC[doc], doc, doc, "reference", judged, note="same rendered PDF"))
        except Exception as exc:
            rows.append(_row("enroll", "setup", PDF_BY_DOC[doc], doc, doc, "reference", {"predicted": None, "status": "error", "error": traceback.format_exc(limit=2)}))
            print(f"  enroll {doc} failed: {exc}", flush=True)

    print("baseline labeled pages", flush=True)
    for doc in PDF_BY_DOC:
        pages = sorted((STAMP_DATASET / doc / "pages").glob("*.jpg"))
        for index, path in enumerate(pages, start=1):
            label = _label_from_name(path.name)
            try:
                judged = _judge(store, doc, _rgb(path))
            except Exception as exc:
                judged = {"predicted": None, "status": "error", "error": str(exc), "stamp_detected": False}
            rows.append(_row("labeled_page", "original", path.name, doc, doc, label, judged))
            if index % 25 == 0:
                print(f"  {doc} {index}/{len(pages)}", flush=True)

    print("other organizations", flush=True)
    for enrolled in PDF_BY_DOC:
        for foreign in PDF_BY_DOC:
            if foreign == enrolled:
                continue
            if foreign in enrolled_pages:
                judged = _judge(store, enrolled, enrolled_pages[foreign])
                rows.append(_row("foreign_pdf", "original", PDF_BY_DOC[foreign], foreign, enrolled, "other_legitimate", judged))
            foreign_pages = [path for path in sorted((STAMP_DATASET / foreign / "pages").glob("*_reference.jpg")) if _held_out(path.name)]
            for path in foreign_pages:
                judged = _judge(store, enrolled, _rgb(path))
                rows.append(_row("foreign_page", "original", path.name, foreign, enrolled, "other_legitimate", judged, note="filename holdout reference of another family"))

    print("genuine page variations", flush=True)
    for doc, page in enrolled_pages.items():
        image = Image.fromarray(page)
        for name, severity, transform in _page_transforms():
            try:
                changed = transform(image)
                judged = _judge(store, doc, np.asarray(changed.convert("RGB")))
                error = ""
            except Exception as exc:
                judged = {"predicted": None, "status": "error", "error": str(exc), "stamp_detected": False}
                error = str(exc)
            row = _row("variation", severity, f"{doc}:{name}", doc, doc, "reference", judged, note=name)
            if error and not row["error"]:
                row["error"] = error
            rows.append(row)
        print(f"  variations {doc}", flush=True)

    print("controlled edits", flush=True)
    for doc, page in enrolled_pages.items():
        region = find_marks(page).get("stamp")
        if region is None:
            rows.append(_row("edit", "setup", doc, doc, doc, "controlled_edit", {"predicted": None, "status": "missing", "stamp_detected": False, "error": "no crop"}))
            continue
        from fraud_detection.documents.specimens import crop_array

        crop = Image.fromarray(crop_array(page, region))
        for name, severity, edited in _edits(crop):
            try:
                judged = _judge(store, doc, _paste(edited))
            except Exception as exc:
                judged = {"predicted": None, "status": "error", "error": str(exc), "stamp_detected": False}
            rows.append(_row("controlled_edit", severity, f"{doc}:{name}", doc, doc, "controlled_edit", judged, note=name))

    print("edge cases", flush=True)
    capital = enrolled_pages.get("capital")
    if capital is not None:
        region = find_marks(capital).get("stamp")
        from fraud_detection.documents.specimens import crop_array

        crop = Image.fromarray(crop_array(capital, region)) if region is not None else None
        edges: list[tuple[str, np.ndarray, str]] = []
        edges.append(("blank", np.full((600, 500, 3), 255, np.uint8), "missing stamp"))
        if crop is not None:
            edges.append(("faint", _paste(ImageEnhance.Brightness(crop).enhance(0.45)), "faint genuine crop"))
            edges.append(("cutoff", _paste(crop, shift=(-40, 40)), "crop hanging off the left edge"))
            tiny = crop.resize((max(8, crop.width // 5), max(8, crop.height // 5)))
            edges.append(("tiny", _paste(tiny), "stamp reduced to one fifth"))
            edges.append(("near_edge", _paste(crop, shift=(820, 20), size=(900, 400)), "stamp against the top-right edge"))
            logo = Image.new("RGB", (900, 1200), (255, 255, 255))
            logo_draw = logo.copy()
            arr = np.asarray(logo_draw)
            arr = arr.copy()
            arr[40:180, 40:180] = (20, 90, 200)
            edges.append(("blue_square", arr, "colored block with no stamp text"))
            both = Image.new("RGB", (1000, 800), (255, 255, 255))
            both.paste(crop, (40, 40))
            if "subvention" in enrolled_pages:
                other_region = find_marks(enrolled_pages["subvention"]).get("stamp")
                if other_region is not None:
                    both.paste(Image.fromarray(crop_array(enrolled_pages["subvention"], other_region)), (520, 40))
            edges.append(("two_stamps", np.asarray(both), "capital crop and subvention crop; capital is enrolled"))
            gray_page = Image.fromarray(capital).convert("L").convert("RGB")
            edges.append(("gray_pdf_page", np.asarray(gray_page), "grayscale copy of the enrolled capital page"))
            low = Image.fromarray(capital).resize((capital.shape[1] // 3, capital.shape[0] // 3), Image.Resampling.BILINEAR)
            low = low.resize((capital.shape[1], capital.shape[0]), Image.Resampling.BILINEAR)
            edges.append(("low_resolution", np.asarray(low), "downscaled and restored"))
        for name, image, note in edges:
            try:
                judged = _judge(store, "capital", image)
            except Exception as exc:
                judged = {"predicted": None, "status": "error", "error": str(exc), "stamp_detected": False}
            rows.append(_row("edge", name, f"capital:{name}", "capital", "capital", "edge", judged, note=note))
        empty = store.check("nobody", capital, expect_signature=False)
        nobody = empty["matches"]["stamp"]
        rows.append(_row("edge", "no_enrollment", "capital_pdf", "capital", "nobody", "no_reference", {"predicted": nobody.get("verdict"), "status": nobody.get("status"), "stamp_detected": True, "error": ""}, note="company with no saved stamp"))

    print("api workflow", flush=True)
    api_results = _api_workflow(rows)

    labeled = [row for row in rows if row["category"] == "labeled_page"]
    baseline = _metrics(labeled)
    holdout = _metrics([row for row in labeled if row["held_out"] is True or row["held_out"] == "True"])
    # csv writes bools as True/False; in-memory they are bools
    holdout = _metrics([row for row in labeled if bool(row["held_out"])])
    variations = _variation_summary([row for row in rows if row["category"] == "variation"])
    edits = [row for row in rows if row["category"] == "controlled_edit"]
    foreign = [row for row in rows if row["category"] in {"foreign_page", "foreign_pdf"}]
    false_accepts = [row for row in labeled if row["ground_truth"] == "counterfeit" and row["predicted"] == "genuine"]
    false_rejects = [row for row in rows if row["ground_truth"] == "reference" and row["predicted"] == "fraudulent"]
    by_doc = {}
    for doc in PDF_BY_DOC:
        by_doc[doc] = _metrics([row for row in labeled if row["source_doc"] == doc])

    accepted = len(false_accepts)
    assessment = (
        "The four enrolled genuine PDFs can be recognized, and a different organization's stamp is not automatically called fraudulent. "
        "The system is a stamp similarity and anomaly screening prototype, not a guaranteed forgery detector. "
        f"On the labeled pages, {accepted} counterfeit page"
        f"{'s were' if accepted != 1 else ' was'} accepted as genuine. "
        "Most counterfeits are uncertain or unrecognized, which asks for a person rather than declaring fraud. "
        "There are only four stamp identities. The 400 pages are scan and mutation variants of those four, and the LightGBM model was trained on this same set. "
        "That is not an independent live-counterfeit trial."
    )
    report = {
        "output_dir": str(OUT),
        "n_cases": len(rows),
        "seed": SEED,
        "labels_csv_present": False,
        "inventory_note": (
            "Four fictitious stamp identities, 50 reference pages and 50 counterfeit pages each (400 labeled pages), plus four genuine PDFs. "
            "Filename suffix is the only label in this checkout. `labels.csv` (difficulty, mutations) described in the dataset README is absent. "
            "Reference pages are scan-style copies of one stamp per document. Counterfeit pages are generated mutations of that stamp, not photographed forgeries."
        ),
        "limitation": (
            "Do not read these rates as performance on unseen printed forgeries. The supervised stamp model was trained on crops from these same four documents. "
            "Generated variations and single-feature edits are stress tests. They are counted separately and are not extra real counterfeits."
        ),
        "baseline_same_family": baseline,
        "baseline_by_doc": by_doc,
        "baseline_filename_holdout": holdout,
        "variations": variations,
        "edits": {
            "n": len(edits),
            "genuine": sum(row["predicted"] == "genuine" for row in edits),
            "fraudulent": sum(row["predicted"] == "fraudulent" for row in edits),
            "uncertain": sum(row["predicted"] == "uncertain" for row in edits),
            "unrecognized": sum(row["predicted"] == "unrecognized" for row in edits),
        },
        "foreign": {
            "n": len(foreign),
            "unrecognized": sum(row["predicted"] == "unrecognized" for row in foreign),
            "uncertain": sum(row["predicted"] == "uncertain" for row in foreign),
            "genuine": sum(row["predicted"] == "genuine" for row in foreign),
            "fraudulent": sum(row["predicted"] == "fraudulent" for row in foreign),
        },
        "api": api_results,
        "false_accept_ids": [
            {key: row[key] for key in ("sample_id", "enrolled_doc", "alignment_ncc", "genuine_probability", "status", "read_text")}
            for row in false_accepts
        ],
        "false_reject_ids": [
            {key: row[key] for key in ("sample_id", "category", "severity", "alignment_ncc", "genuine_probability", "source_doc")}
            for row in false_rejects
        ],
        "edge": [
            {key: row[key] for key in ("sample_id", "predicted", "status", "stamp_detected", "error", "note")}
            for row in rows
            if row["category"] == "edge"
        ],
        "assessment": assessment,
    }
    _write_csv(OUT / "cases.csv", rows)
    (OUT / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "summary.md").write_text(_markdown(report), encoding="utf-8")
    shutil.rmtree(store_root, ignore_errors=True)
    print(f"wrote {OUT} cases={len(rows)}", flush=True)
    print(
        "baseline accept",
        baseline["genuine_acceptance_rate"],
        "false accept",
        baseline["counterfeit_false_accept_rate"],
        "detect",
        baseline["counterfeit_detection_rate"],
        flush=True,
    )


if __name__ == "__main__":
    main()
