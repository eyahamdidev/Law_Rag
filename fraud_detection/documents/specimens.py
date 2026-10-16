"""Crop a stamp or signature and compare it with the genuine one a user enrolled.

The enrollment directory starts empty. Nothing is saved until that user approves
a crop and attaches a comment. A later page is judged against that saved crop.

Stamps use a supervised verifier trained on labeled genuine and counterfeit
pairs. It is not an anomaly detector and it is not a YOLO model. The words on
the crop decide which question to ask. The same wording and the same drawing
is genuine, including a photograph of the saved stamp. A hole in an otherwise
matching drawing is fraudulent and is not offered for enrollment. The same
wording with a text-line profile worse than a harmless recapture of the saved
stamp is fraudulent. A low alignment score is uncertain, not fraudulent. A
different wording is unrecognized: the service asks whether to save it as
another genuine stamp.
"""

from __future__ import annotations

import base64
import io
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from fraud_detection.documents.stamp_alignment import (
    compare_drawings,
    crop_quality,
    harmless_row_floor,
    review_triage,
    stamp_decision,
)
from fraud_detection.documents.stamp_content import content_relation, read_stamp_text
from fraud_detection.paths import PACKAGE, STAMP_VERIFIER

KINDS = ("stamp", "signature")
SHAPE_THRESHOLD = 0.92
SIZE_TOLERANCE = 0.06
_CLOSE_LOOK = 0.70
_MAX_SIDE = 1200
# Labeled A4 scans are 1404 px on the long side. The genuine PDF is rendered
# at about 1348 px and then limited to 1200. Shrinking the scan to 1200 as
# well blurs the ink, and a close genuine capital scan then scores below a
# subtle counterfeit. Uploaded scans stay at their own size up to 1600 px,
# which is the resolution the alignment rule was measured against.
_SCAN_MAX_SIDE = 1600
_MAX_BYTES = 8_000_000
_SAVE_QUESTIONS = {
    "stamp": "A stamp was found and cropped from this file. Save it for {entity_id} so later documents can be compared with it?",
    "signature": "A signature was found and cropped from this file. Save it for {entity_id} so later documents can be compared with it?",
}
_NEW_QUESTIONS = {
    "stamp": "This stamp does not match a stamp saved for {entity_id}. Save it as a new genuine stamp? Declining keeps the warning and does not enroll it.",
    "signature": "This signature does not match a signature saved for {entity_id}. Save it as a new genuine signature? Declining keeps the warning and does not enroll it.",
}


def tenant_key(*candidates: str | None) -> str | None:
    """First non-blank organization id. A blank string is not a shared tenant."""
    for candidate in candidates:
        text = " ".join((candidate or "").split())
        if text:
            return text
    return None


def specimen_dir() -> Path:
    override = os.environ.get("FRAUD_SPECIMEN_DIR")
    path = Path(override) if override else PACKAGE / "data" / "specimens"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _to_gray(image: Image.Image) -> np.ndarray:
    gray = image.convert("L")
    gray.thumbnail((_MAX_SIDE, _MAX_SIDE))
    return np.asarray(gray, dtype=np.uint8)


def limit_rgb(image: Image.Image) -> np.ndarray:
    rgb = image.convert("RGB")
    rgb.thumbnail((_MAX_SIDE, _MAX_SIDE))
    return np.asarray(rgb, dtype=np.uint8)


def decode_image(image_base64: str) -> np.ndarray:
    raw = base64.b64decode(image_base64, validate=False)
    if not raw:
        raise ValueError("empty image")
    if len(raw) > _MAX_BYTES:
        raise ValueError("image_too_large")
    rgb = Image.open(io.BytesIO(raw)).convert("RGB")
    rgb.thumbnail((_SCAN_MAX_SIDE, _SCAN_MAX_SIDE))
    return np.asarray(rgb, dtype=np.uint8)


def page_gray(page: np.ndarray) -> np.ndarray:
    if page.ndim == 2:
        return page
    channels = page.astype(np.float32)
    return (0.299 * channels[:, :, 0] + 0.587 * channels[:, :, 1] + 0.114 * channels[:, :, 2]).astype(np.uint8)


def clean_comment(comment: str | None, kind: str, entity_id: str) -> str:
    text = " ".join((comment or "").split())
    if not text:
        noun = "stamp" if kind == "stamp" else "signature"
        text = f"Genuine {noun} enrolled for {entity_id}."
    return text[:240]


def crop_png_base64(page: np.ndarray, region: dict) -> str:
    crop = crop_array(page, region)
    buffer = io.BytesIO()
    if crop.ndim == 2:
        Image.fromarray(crop, mode="L").save(buffer, format="PNG")
    else:
        Image.fromarray(crop, mode="RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    return gray < 160


def _components(mask: np.ndarray) -> list[dict]:
    labels, count = ndimage.label(np.asarray(mask, dtype=bool))
    if count == 0:
        return []
    found: list[dict] = []
    for index, slc in enumerate(ndimage.find_objects(labels), start=1):
        if slc is None:
            continue
        area = int(np.count_nonzero(labels[slc] == index))
        if area <= 0:
            continue
        min_y, min_x = int(slc[0].start), int(slc[1].start)
        max_y, max_x = int(slc[0].stop - 1), int(slc[1].stop - 1)
        found.append(
            {
                "min_x": min_x,
                "min_y": min_y,
                "max_x": max_x,
                "max_y": max_y,
                "area": area,
                "width": max_x - min_x + 1,
                "height": max_y - min_y + 1,
            }
        )
    return found


def _classify(region: dict, page_h: int, page_w: int) -> str | None:
    area_ratio = region["area"] / max(1, page_h * page_w)
    if area_ratio < 0.002 or area_ratio > 0.20:
        return None
    aspect = region["width"] / max(1, region["height"])
    density = region["area"] / max(1, region["width"] * region["height"])
    center_y = (region["min_y"] + region["max_y"]) / 2 / page_h
    if 0.65 <= aspect <= 1.55 and 0.12 <= density <= 0.80 and region["width"] >= page_w * 0.05:
        return "stamp"
    if aspect >= 1.7 and 0.015 <= density <= 0.35 and center_y >= 0.35 and region["width"] >= page_w * 0.08:
        return "signature"
    return None


def _boxes_close(left: dict, right: dict, gap: int) -> bool:
    return not (
        left["max_x"] + gap < right["min_x"]
        or right["max_x"] + gap < left["min_x"]
        or left["max_y"] + gap < right["min_y"]
        or right["max_y"] + gap < left["min_y"]
    )


def _union_box(regions: list[dict]) -> dict:
    min_x = min(region["min_x"] for region in regions)
    min_y = min(region["min_y"] for region in regions)
    max_x = max(region["max_x"] for region in regions)
    max_y = max(region["max_y"] for region in regions)
    area = sum(region["area"] for region in regions)
    return {
        "min_x": min_x,
        "min_y": min_y,
        "max_x": max_x,
        "max_y": max_y,
        "area": area,
        "width": max_x - min_x + 1,
        "height": max_y - min_y + 1,
    }


def _color_mask(page: np.ndarray, chroma_min: int = 28) -> np.ndarray | None:
    if page.ndim != 3:
        return None
    red = page[:, :, 0].astype(np.int16)
    green = page[:, :, 1].astype(np.int16)
    blue = page[:, :, 2].astype(np.int16)
    chroma = np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue)
    gray = page_gray(page).astype(np.int16)
    return (chroma >= chroma_min) & (gray < 235)


def _grouped_boxes(mask: np.ndarray, min_area: int) -> list[dict]:
    height = mask.shape[0]
    gap = max(18, int(0.02 * height))
    pieces = [region for region in _components(mask) if region["area"] >= min_area]
    if not pieces:
        return []
    parent = list(range(len(pieces)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left_index, left in enumerate(pieces):
        for right_index in range(left_index + 1, len(pieces)):
            if _boxes_close(left, pieces[right_index], gap):
                parent[find(right_index)] = find(left_index)
    groups: dict[int, list[dict]] = {}
    for index, region in enumerate(pieces):
        groups.setdefault(find(index), []).append(region)
    return [_union_box(group) for group in groups.values()]


def _color_stamp(page: np.ndarray) -> dict | None:
    # 28 is the tight mask. A light-blue text stamp falls apart under JPEG at
    # that cutoff, so a miss is retried at 20. Starting at 20 pulls noise into
    # a box that already matched and can prefer the larger of two stamps.
    found = _color_stamp_at(page, 28)
    if found is not None:
        return found
    return _color_stamp_at(page, 20)


def _color_stamp_at(page: np.ndarray, chroma_min: int) -> dict | None:
    mask = _color_mask(page, chroma_min)
    if mask is None or not mask.any():
        return None
    height, width = mask.shape
    best = None
    best_area = 0
    for box in _grouped_boxes(mask, 40):
        aspect = box["width"] / max(1, box["height"])
        area_ratio = box["area"] / max(1, height * width)
        touches_edge = (
            box["min_x"] <= 2
            or box["min_y"] <= 2
            or box["max_x"] >= width - 3
            or box["max_y"] >= height - 3
        )
        min_width = width * (0.06 if touches_edge else 0.10)
        if not (0.40 <= aspect <= 2.8 and box["width"] >= min_width and box["height"] >= height * 0.06):
            continue
        if not (0.0008 <= area_ratio <= 0.22):
            continue
        if box["area"] > best_area:
            best = box
            best_area = box["area"]
    return best


def _gray_stamp(page: np.ndarray) -> dict | None:
    """Group light-gray ink when the page has no color to follow.

    A grayscale copy of a blue stamp sits just under the paper, so a fixed
    cutoff of 160 drops it. Body text is much darker and spans the page, so
    a stamp-shaped box that is not page-wide is kept.

    Near-black ink (chroma under 20) never reaches the color finder. On a
    short page patch that stamp is a large share of the image: about 0.55 of
    the width and 0.49 of the height, with a rotated rectangle near aspect
    2.12. The full-page caps (width 0.48, height 0.30, aspect 2.05) dropped
    those boxes. Width stays at 0.72 because the body-text block on the four
    genuine PDFs is about 0.79 of the page width, and that block must not
    become the stamp. Ink area stays at 0.05 for the same reason.
    """
    gray = page_gray(page)
    height, width = gray.shape
    paper = float(np.percentile(gray, 92))
    level = min(paper - 18.0, 210.0)
    if level < 40:
        return None
    best = None
    best_area = 0
    for box in _grouped_boxes(gray < level, 30):
        aspect = box["width"] / max(1, box["height"])
        area_ratio = box["area"] / max(1, height * width)
        width_ratio = box["width"] / max(1, width)
        if not (0.70 <= aspect <= 2.25):
            continue
        if not (0.12 <= width_ratio <= 0.72):
            continue
        if box["height"] < height * 0.05 or box["height"] > height * 0.55:
            continue
        if not (0.0008 <= area_ratio <= 0.05):
            continue
        if box["area"] > best_area:
            best = box
            best_area = box["area"]
    return best


def _has_color_ink(crop: np.ndarray) -> bool:
    mask = _color_mask(crop)
    if mask is None or mask.size == 0:
        return False
    return float(mask.mean()) >= 0.02


def find_marks(page: np.ndarray) -> dict[str, dict | None]:
    gray = page_gray(page)
    height, width = gray.shape
    chosen: dict[str, dict | None] = {"stamp": None, "signature": None}
    best_area = {"stamp": 0, "signature": 0}
    for region in _components(_ink_mask(gray)):
        kind = _classify(region, height, width)
        if kind is None:
            continue
        if region["area"] > best_area[kind]:
            best_area[kind] = region["area"]
            chosen[kind] = region
    colored = _color_stamp(page)
    if colored is not None and (chosen["stamp"] is None or colored["area"] > chosen["stamp"]["area"]):
        chosen["stamp"] = colored
    if chosen["stamp"] is None:
        gray_stamp = _gray_stamp(page)
        if gray_stamp is not None:
            chosen["stamp"] = gray_stamp
    return chosen


def crop_array(page: np.ndarray, region: dict, pad: int = 4) -> np.ndarray:
    y0 = max(0, region["min_y"] - pad)
    y1 = min(page.shape[0], region["max_y"] + 1 + pad)
    x0 = max(0, region["min_x"] - pad)
    x1 = min(page.shape[1], region["max_x"] + 1 + pad)
    return page[y0:y1, x0:x1]


def _fingerprint(page: np.ndarray, region: dict) -> np.ndarray:
    gray = page_gray(page)
    pad = 2
    y0 = max(0, region["min_y"] - pad)
    y1 = min(gray.shape[0], region["max_y"] + 1 + pad)
    x0 = max(0, region["min_x"] - pad)
    x1 = min(gray.shape[1], region["max_x"] + 1 + pad)
    crop = gray[y0:y1, x0:x1]
    image = Image.fromarray(crop, mode="L").resize((96, 96), Image.Resampling.BOX)
    ink = (np.asarray(image, dtype=np.float32) < 160).astype(np.float32)
    norm = float(np.linalg.norm(ink))
    if norm == 0:
        return ink.reshape(-1)
    return (ink / norm).reshape(-1)


def _similarity(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right))


def _measures(page: np.ndarray, region: dict) -> dict[str, float]:
    page_h, page_w = page_gray(page).shape
    return {
        "width_ratio": region["width"] / page_w,
        "height_ratio": region["height"] / page_h,
        "aspect": region["width"] / max(1, region["height"]),
        "density": region["area"] / max(1, region["width"] * region["height"]),
    }


def _relative_gap(left: float, right: float) -> float:
    return abs(left - right) / max(abs(right), 1e-6)


def _differences(shape_score: float, current: dict[str, float], saved: dict[str, float]) -> list[str]:
    found: list[str] = []
    if _relative_gap(current["width_ratio"], saved["width_ratio"]) > SIZE_TOLERANCE or _relative_gap(
        current["height_ratio"], saved["height_ratio"]
    ) > SIZE_TOLERANCE:
        found.append("size")
    if _relative_gap(current["aspect"], saved["aspect"]) > SIZE_TOLERANCE or _relative_gap(
        current["density"], saved["density"]
    ) > 0.12:
        found.append("shape")
    if shape_score < SHAPE_THRESHOLD:
        found.append("shape")
    return list(dict.fromkeys(found))


def _mark_row(
    kind: str,
    *,
    status: str,
    page: int | None = None,
    similarity: float | None = None,
    specimen_id: str | None = None,
    differences: list[str] | None = None,
    proposal_id: str | None = None,
    crop_base64: str | None = None,
    question: str | None = None,
    verdict: str | None = None,
    genuine_probability: float | None = None,
    comment: str | None = None,
    read_text: str | None = None,
    enrolled_text: str | None = None,
    alignment_ncc: float | None = None,
    review_reason: str | None = None,
    reason_codes: list[str] | None = None,
    evidence: dict | None = None,
) -> dict:
    return {
        "kind": kind,
        "page": page,
        "status": status,
        "similarity": similarity,
        "specimen_id": specimen_id,
        "differences": differences or [],
        "proposal_id": proposal_id,
        "crop_base64": crop_base64,
        "question": question,
        "verdict": verdict,
        "genuine_probability": genuine_probability,
        "comment": comment,
        "read_text": read_text,
        "enrolled_text": enrolled_text,
        "alignment_ncc": alignment_ncc,
        "review_reason": review_reason,
        "reason_codes": list(reason_codes or []),
        "evidence": dict(evidence or {}),
        **review_triage(verdict if verdict is not None else ("missing" if status == "missing" else None), reason_codes),
    }


def _clip_text(text: str, limit: int = 90) -> str:
    words = " ".join((text or "").split())
    if len(words) <= limit:
        return words
    return words[: limit - 3].rstrip() + "..."


def _unrecognized_question(kind: str, entity_id: str, read_text: str, enrolled_text: str) -> str:
    noun = "stamp" if kind == "stamp" else "signature"
    if read_text and enrolled_text:
        return (
            f"This {noun} reads \"{_clip_text(read_text)}\". "
            f"The saved {noun} reads \"{_clip_text(enrolled_text)}\". "
            f"The content is not the same. Save it as a new genuine {noun}?"
        )
    return _NEW_QUESTIONS[kind].format(entity_id=entity_id)


def _note_inserted_image(marks: list[dict], forensics: dict | None) -> None:
    """A separate PDF image is a clue, not proof the stamp was pasted.

    The genuine labellisation PDF already contains one image object, and a
    scanned PDF can be a single image. The clue is recorded only when the
    verdict is already uncertain or unrecognized.
    """
    if not forensics or not forensics.get("available"):
        return
    images = int(forensics.get("image_objects") or 0)
    if images <= 0:
        return
    for mark in marks:
        if mark.get("kind") != "stamp" or mark.get("verdict") not in {"uncertain", "unrecognized"}:
            continue
        codes = list(mark.get("reason_codes") or [])
        if "possible_inserted_image" not in codes:
            codes.append("possible_inserted_image")
        mark["reason_codes"] = codes
        evidence = dict(mark.get("evidence") or {})
        evidence["pdf_image_objects"] = images
        evidence["pdf_drawings"] = forensics.get("drawings")
        evidence["possible_inserted_image"] = "clue_not_proof"
        mark["evidence"] = evidence
        mark.update(review_triage(mark.get("verdict"), codes))


def _evidence(content: str, alignment: dict) -> dict:
    """Measurements the verdict actually looked at. The model score is not one of them."""
    return {
        "content": content,
        "quality": alignment.get("quality"),
        "ncc": alignment.get("ncc"),
        "local_min": alignment.get("local_min"),
        "row_corr": alignment.get("row_corr"),
        "row_floor": alignment.get("row_floor"),
        "mae": alignment.get("mae"),
        "low_block": alignment.get("low_block"),
        "worst_block": alignment.get("worst_block"),
        "worst_cell": alignment.get("worst_cell"),
        "block_map": alignment.get("block_map"),
        "bright_peak": alignment.get("bright_peak"),
        "dark_peak": alignment.get("dark_peak"),
        "model_score_used": False,
        "exact_stamp_copy_from_crop_alone": False,
    }


def _uncertain_question(kind: str) -> str:
    noun = "stamp" if kind == "stamp" else "signature"
    return (
        f"This {noun} is not clear enough to call genuine or fraudulent. "
        "Review it manually. It has not been enrolled."
    )


def _verdict_for(
    kind: str,
    content: str,
    differences: list[str],
    score: float,
    *,
    exact: bool = False,
) -> str:
    """Same wording is genuine or fraudulent. Different wording is unrecognized.

    An exact drawing is the saved stamp even when OCR is noisy. Different
    wording is never called fraudulent. The same wording with any remaining
    gap in the drawing is fraudulent and is not offered for enrollment.
    """
    if exact:
        return "genuine"
    if kind == "stamp" and content == "different":
        return "unrecognized"
    if kind == "stamp" and content == "same":
        return "genuine" if not differences else "fraudulent"
    if not differences:
        return "genuine"
    if score >= _CLOSE_LOOK:
        return "fraudulent"
    return "unrecognized"


class SpecimenStore:
    def __init__(self, root: Path | None = None):
        self.root = root or specimen_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.proposals_path = self.root / "proposals.json"
        self._verifier = None
        self._verifier_ready = False
        self._row_floors: dict[str, float | None] = {}

    def _load(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        return list(payload.get("specimens") or [])

    def _save(self, rows: list[dict]) -> None:
        self.index_path.write_text(json.dumps({"specimens": rows}, indent=2) + "\n", encoding="utf-8")

    def _load_proposals(self) -> list[dict]:
        if not self.proposals_path.exists():
            return []
        payload = json.loads(self.proposals_path.read_text(encoding="utf-8"))
        return list(payload.get("proposals") or [])

    def _save_proposals(self, rows: list[dict]) -> None:
        self.proposals_path.write_text(json.dumps({"proposals": rows}, indent=2) + "\n", encoding="utf-8")

    def enrolled_count(self) -> int:
        return len(self._load())

    def _tenants_path(self) -> Path:
        return self.root / "tenants.json"

    def _tenant_secrets(self) -> dict[str, str]:
        path = self._tenants_path()
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in (payload.get("secrets") or {}).items()}

    def _write_tenant_secrets(self, secrets_by_tenant: dict[str, str]) -> None:
        self._tenants_path().write_text(
            json.dumps({"secrets": secrets_by_tenant}, indent=2) + "\n",
            encoding="utf-8",
        )

    def issue_tenant_secret(self, entity_id: str) -> str:
        """Stable secret for one organization. Returned to the caller who enrolled it."""
        tenant = tenant_key(entity_id)
        if tenant is None:
            raise ValueError("missing_tenant")
        current = self._tenant_secrets()
        existing = current.get(tenant)
        if existing:
            return existing
        current[tenant] = secrets.token_hex(16)
        self._write_tenant_secrets(current)
        return current[tenant]

    def tenant_is_locked(self, entity_id: str) -> bool:
        tenant = tenant_key(entity_id)
        if tenant is None:
            return False
        return any(row.get("entity_id") == tenant for row in self._load())

    def tenant_authorized(self, entity_id: str, presented: str | None) -> bool:
        """A locked organization is readable only with the secret from enrollment.

        An organization with no saved reference is not locked, so the first
        proposal can be made. Knowing the organization id is not enough after that.
        """
        tenant = tenant_key(entity_id)
        if tenant is None or not self.tenant_is_locked(tenant):
            return True
        stored = self._tenant_secrets().get(tenant)
        offered = " ".join((presented or "").split())
        if not stored or not offered:
            return False
        return secrets.compare_digest(stored, offered)

    def verifier(self):
        if self._verifier_ready:
            return self._verifier
        self._verifier_ready = True
        override = os.environ.get("FRAUD_STAMP_MODEL")
        path = Path(override) if override else STAMP_VERIFIER
        if path.is_file():
            from fraud_detection.documents.stamp_verifier import StampVerifier

            self._verifier = StampVerifier.load(path)
        return self._verifier

    def _row_floor_for(self, specimen_id: str, row: dict, crop: np.ndarray) -> float | None:
        """Cached text-line floor for one enrolled stamp. Computed once per process if missing."""
        stored = row.get("row_floor")
        if stored is not None:
            return float(stored)
        if specimen_id in self._row_floors:
            return self._row_floors[specimen_id]
        floor = harmless_row_floor(crop)
        self._row_floors[specimen_id] = floor
        return floor

    def _load_crop(self, specimen_id: str) -> np.ndarray | None:
        path = self.root / f"{specimen_id}.png"
        if not path.is_file():
            return None
        return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)

    def _propose(self, entity_id: str, kind: str, page: np.ndarray, comment: str | None = None) -> str:
        proposal_id = uuid.uuid4().hex
        np.save(self.root / f"{proposal_id}.page.npy", page)
        rows = self._load_proposals()
        rows.append(
            {
                "proposal_id": proposal_id,
                "entity_id": entity_id,
                "kind": kind,
                "status": "pending",
                "comment": comment,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._save_proposals(rows)
        return proposal_id

    def enroll(self, entity_id: str, kind: str, page: np.ndarray, comment: str | None = None) -> dict:
        tenant = tenant_key(entity_id)
        if tenant is None:
            return {
                "enrolled": False,
                "reason": "missing_tenant",
                "specimen_id": None,
                "kind": kind,
                "entity_id": None,
                "comment": None,
                "crop_base64": None,
            }
        if kind not in KINDS:
            raise ValueError("kind must be stamp or signature")
        region = find_marks(page)[kind]
        if region is None:
            return {
                "enrolled": False,
                "reason": f"no_{kind}_region",
                "specimen_id": None,
                "kind": kind,
                "entity_id": entity_id,
                "comment": None,
                "crop_base64": None,
            }
        text = clean_comment(comment, kind, tenant)
        crop = crop_array(page, region)
        read_text = read_stamp_text(crop) if kind == "stamp" else ""
        row_floor = harmless_row_floor(crop) if kind == "stamp" else None
        fingerprint = _fingerprint(page, region)
        measures = _measures(page, region)
        specimen_id = uuid.uuid4().hex[:12]
        np.save(self.root / f"{specimen_id}.npy", fingerprint)
        Image.fromarray(crop if crop.ndim == 3 else np.stack([crop, crop, crop], axis=-1), mode="RGB").save(
            self.root / f"{specimen_id}.png"
        )
        rows = self._load()
        rows.append(
            {
                "specimen_id": specimen_id,
                "entity_id": tenant,
                "kind": kind,
                "comment": text,
                "read_text": read_text,
                "row_floor": row_floor,
                "created_at": datetime.now(timezone.utc).isoformat(),
                **measures,
            }
        )
        self._save(rows)
        return {
            "enrolled": True,
            "reason": "saved",
            "specimen_id": specimen_id,
            "kind": kind,
            "entity_id": tenant,
            "comment": text,
            "read_text": read_text,
            "crop_base64": crop_png_base64(page, region),
            "tenant_secret": self.issue_tenant_secret(tenant),
        }

    def decide(self, proposal_id: str, approve: bool, comment: str | None = None, tenant_secret: str | None = None) -> dict:
        rows = self._load_proposals()
        row = next((item for item in rows if item.get("proposal_id") == proposal_id), None)
        empty = {
            "proposal_id": proposal_id,
            "decision": None,
            "enrolled": False,
            "reason": "unknown_proposal",
            "specimen_id": None,
            "kind": None,
            "entity_id": None,
            "comment": None,
        }
        if row is None:
            return empty
        entity = row.get("entity_id")
        if entity and self.tenant_is_locked(str(entity)) and not self.tenant_authorized(str(entity), tenant_secret):
            return {
                **empty,
                "reason": "tenant_unauthorized",
                "kind": row.get("kind"),
                "entity_id": entity,
            }
        if row.get("status") != "pending":
            return {
                **empty,
                "decision": row.get("status"),
                "reason": "already_decided",
                "specimen_id": row.get("specimen_id"),
                "kind": row.get("kind"),
                "entity_id": row.get("entity_id"),
                "comment": row.get("comment"),
            }
        path = self.root / f"{proposal_id}.page.npy"
        if not approve:
            row["status"] = "declined"
            self._save_proposals(rows)
            path.unlink(missing_ok=True)
            return {
                **empty,
                "decision": "declined",
                "reason": "declined",
                "kind": row.get("kind"),
                "entity_id": row.get("entity_id"),
            }
        if not path.exists():
            row["status"] = "missing_file"
            self._save_proposals(rows)
            return {
                **empty,
                "decision": "missing_file",
                "reason": "missing_file",
                "kind": row.get("kind"),
                "entity_id": row.get("entity_id"),
            }
        page = np.load(path)
        result = self.enroll(
            str(row["entity_id"]),
            str(row["kind"]),
            page,
            comment=comment if comment is not None else row.get("comment"),
        )
        row["status"] = "approved" if result["enrolled"] else "enroll_failed"
        row["specimen_id"] = result.get("specimen_id")
        row["reason"] = result.get("reason")
        row["comment"] = result.get("comment")
        self._save_proposals(rows)
        path.unlink(missing_ok=True)
        return {
            "proposal_id": proposal_id,
            "decision": "approved" if result["enrolled"] else "not_saved",
            "enrolled": bool(result["enrolled"]),
            "reason": result.get("reason"),
            "specimen_id": result.get("specimen_id"),
            "kind": row.get("kind"),
            "entity_id": row.get("entity_id"),
            "comment": result.get("comment"),
            "tenant_secret": result.get("tenant_secret"),
        }

    def review_pages(
        self,
        entity_id: str,
        pages: list[np.ndarray],
        *,
        expect_stamp: bool = True,
        expect_signature: bool = True,
        source: str = "image",
        text_excerpt: str | None = None,
        comment: str | None = None,
        forensics: dict | None = None,
    ) -> dict:
        tenant = tenant_key(entity_id)
        if tenant is None:
            return {
                "checked": False,
                "source": source,
                "pages": len(pages),
                "warnings": ["missing_tenant"],
                "approval_required": False,
                "marks": [],
                "proof": False,
                "text_excerpt": None,
                "note": "No organization id was provided. The file was not compared and nothing was saved.",
            }
        found: dict[str, tuple[int, np.ndarray, dict]] = {}
        for index, gray in enumerate(pages):
            marks = find_marks(gray)
            for kind in KINDS:
                if marks[kind] is not None and kind not in found:
                    found[kind] = (index, gray, marks[kind])
        warnings: list[str] = []
        reported: list[dict] = []
        approval_required = False
        expected = {"stamp": expect_stamp, "signature": expect_signature}
        for kind in KINDS:
            located = found.get(kind)
            if located is None:
                if expected[kind]:
                    warnings.append(f"missing_{kind}")
                    reported.append(
                        _mark_row(
                            kind,
                            status="missing",
                            review_reason="missing_stamp" if kind == "stamp" else "missing_signature",
                            reason_codes=["missing_stamp" if kind == "stamp" else "missing_signature"],
                        )
                    )
                continue
            page_index, page, region = located
            judgment = self._judge(tenant, kind, page, region)
            crop = crop_png_base64(page, region)
            page_number = page_index + 1
            if judgment["specimen_id"] is None:
                approval_required = True
                reported.append(
                    _mark_row(
                        kind,
                        status="awaiting_approval",
                        page=page_number,
                        crop_base64=crop,
                        proposal_id=self._propose(tenant, kind, page, comment),
                        question=_SAVE_QUESTIONS[kind].format(entity_id=tenant),
                        comment=comment,
                        review_reason="insufficient_reference",
                        reason_codes=["insufficient_reference"],
                    )
                )
                continue
            if judgment["verdict"] == "fraudulent":
                warnings.append(f"{kind}_fraudulent")
                reported.append(
                    _mark_row(
                        kind,
                        status="fraudulent",
                        page=page_number,
                        similarity=round(judgment["score"], 4),
                        specimen_id=judgment["specimen_id"],
                        differences=judgment["differences"],
                        crop_base64=crop,
                        verdict="fraudulent",
                        genuine_probability=judgment["probability"],
                        comment=judgment["comment"],
                        read_text=judgment["read_text"],
                        enrolled_text=judgment["enrolled_text"],
                        alignment_ncc=judgment.get("alignment_ncc"),
                        review_reason=judgment.get("review_reason"),
                        reason_codes=judgment.get("reason_codes"),
                        evidence=judgment.get("evidence"),
                    )
                )
                continue
            if judgment["verdict"] == "uncertain":
                warnings.append(f"{kind}_uncertain")
                reported.append(
                    _mark_row(
                        kind,
                        status="uncertain",
                        page=page_number,
                        similarity=round(judgment["score"], 4),
                        specimen_id=judgment["specimen_id"],
                        differences=judgment["differences"],
                        crop_base64=crop,
                        question=_uncertain_question(kind),
                        verdict="uncertain",
                        genuine_probability=judgment["probability"],
                        comment=judgment["comment"],
                        read_text=judgment["read_text"],
                        enrolled_text=judgment["enrolled_text"],
                        alignment_ncc=judgment.get("alignment_ncc"),
                        review_reason=judgment.get("review_reason"),
                        reason_codes=judgment.get("reason_codes"),
                        evidence=judgment.get("evidence"),
                    )
                )
                continue
            if judgment["verdict"] != "genuine":
                approval_required = True
                warnings.append(f"{kind}_unrecognized")
                reported.append(
                    _mark_row(
                        kind,
                        status="unrecognized",
                        page=page_number,
                        similarity=None if judgment["score"] < 0 else round(judgment["score"], 4),
                        specimen_id=judgment["specimen_id"],
                        differences=judgment["differences"],
                        crop_base64=crop,
                        proposal_id=self._propose(tenant, kind, page, comment),
                        question=_unrecognized_question(
                            kind, tenant, judgment["read_text"], judgment["enrolled_text"]
                        ),
                        verdict="unrecognized",
                        genuine_probability=judgment["probability"],
                        comment=judgment["comment"],
                        read_text=judgment["read_text"],
                        enrolled_text=judgment["enrolled_text"],
                        alignment_ncc=judgment.get("alignment_ncc"),
                        review_reason=judgment.get("review_reason"),
                        reason_codes=judgment.get("reason_codes"),
                        evidence=judgment.get("evidence"),
                    )
                )
                continue
            reported.append(
                _mark_row(
                    kind,
                    status="match",
                    page=page_number,
                    similarity=round(judgment["score"], 4),
                    specimen_id=judgment["specimen_id"],
                    differences=[],
                    crop_base64=crop,
                    verdict="genuine",
                    genuine_probability=judgment["probability"],
                    comment=judgment["comment"],
                    read_text=judgment["read_text"],
                    enrolled_text=judgment["enrolled_text"],
                    alignment_ncc=judgment.get("alignment_ncc"),
                    review_reason=judgment.get("review_reason"),
                    reason_codes=judgment.get("reason_codes"),
                    evidence=judgment.get("evidence"),
                )
            )
        _note_inserted_image(reported, forensics)
        return {
            "checked": True,
            "source": source,
            "pages": len(pages),
            "warnings": warnings,
            "approval_required": approval_required,
            "marks": reported,
            "proof": False,
            "text_excerpt": text_excerpt,
            "forensics": dict(forensics or {"available": False, "reason": "not_a_pdf"}),
            "note": (
                "The stamp was cropped from the uploaded file. Nothing is saved until you approve, "
                "and a fresh user has no enrolled stamp yet. Matching wording and drawing is genuine. "
                "A hole in that drawing is fraudulent. The same wording with a text-line profile "
                "worse than a harmless recapture is fraudulent. A low alignment score alone is uncertain, not fraudulent. "
                "Different wording is unrecognized and can be enrolled as a new genuine stamp. "
                "Each mark includes review_recommended and risk_level. Those queue a person. "
                "They are not a calibrated fraud probability. "
                "This is not proof the document is genuine."
            ),
        }

    def _judge(self, entity_id: str, kind: str, page: np.ndarray, region: dict) -> dict:
        """Same stamp content is genuine or fraudulent. Different content asks to enroll."""
        fingerprint = _fingerprint(page, region)
        measures = _measures(page, region)
        crop = crop_array(page, region)
        read_text = read_stamp_text(crop) if kind == "stamp" else ""
        verifier = self.verifier() if kind == "stamp" else None
        candidates: list[dict] = []
        for row in self._load():
            if row.get("entity_id") != entity_id or row.get("kind") != kind:
                continue
            path = self.root / f"{row['specimen_id']}.npy"
            if not path.exists() or "width_ratio" not in row:
                continue
            score = _similarity(fingerprint, np.load(path))
            differences = _differences(score, measures, row)
            probability = None
            enrolled_crop = self._load_crop(str(row["specimen_id"])) if kind == "stamp" else None
            enrolled_text = str(row.get("read_text") or "")
            if kind == "stamp" and not enrolled_text and enrolled_crop is not None:
                enrolled_text = read_stamp_text(enrolled_crop)
            model_exact = False
            alignment = {"ncc": None, "local_min": None, "angle": 0, "quality": "failed"}
            if kind == "stamp" and enrolled_crop is not None:
                if verifier is not None:
                    judged = verifier.judge(enrolled_crop, crop)
                    probability = judged["genuine_probability"]
                    model_exact = bool(judged.get("exact"))
                alignment = compare_drawings(enrolled_crop, crop)
                alignment["row_floor"] = self._row_floor_for(str(row["specimen_id"]), row, enrolled_crop)
            content = content_relation(enrolled_text, read_text) if kind == "stamp" else "unknown"
            evidence = _evidence(content, alignment) if kind == "stamp" else {}
            if kind == "stamp" and crop_quality(crop) == "unusable":
                verdict = "uncertain"
                reason_codes = ["poor_image_quality"]
                differences = list(dict.fromkeys([*differences, "unclear"]))
            elif kind == "stamp":
                decision = stamp_decision(content, alignment, probability, model_exact)
                verdict = decision["verdict"]
                reason_codes = list(decision["reason_codes"])
                if verdict == "genuine":
                    differences = []
                elif verdict == "fraudulent":
                    differences = list(dict.fromkeys([*differences, "drawing"]))
                elif verdict == "uncertain":
                    differences = list(dict.fromkeys([*differences, "unclear"]))
            else:
                verdict = _verdict_for(kind, content, differences, score)
                reason_codes = []
            if kind == "stamp" and alignment.get("ncc") is not None:
                score = float(alignment["ncc"])
            candidates.append(
                {
                    "score": score,
                    "specimen_id": row["specimen_id"],
                    "differences": [] if verdict == "genuine" else differences,
                    "comment": row.get("comment"),
                    "probability": probability,
                    "verdict": verdict,
                    "read_text": read_text,
                    "enrolled_text": enrolled_text,
                    "alignment_ncc": alignment.get("ncc"),
                    "review_reason": reason_codes[0] if reason_codes else None,
                    "reason_codes": reason_codes,
                    "evidence": evidence,
                }
            )
        if not candidates:
            return {
                "score": -1.0,
                "specimen_id": None,
                "differences": [],
                "comment": None,
                "probability": None,
                "verdict": None,
                "read_text": read_text,
                "enrolled_text": "",
                "alignment_ncc": None,
                "review_reason": "insufficient_reference",
                "reason_codes": ["insufficient_reference"],
                "evidence": {},
            }
        rank = {"genuine": 4, "fraudulent": 3, "uncertain": 2, "unrecognized": 1}
        chosen = max(candidates, key=lambda item: (rank.get(item["verdict"], 0), item["score"]))
        return chosen

    def check(self, entity_id: str, gray: np.ndarray, *, expect_stamp: bool = True, expect_signature: bool = True) -> dict:
        tenant = tenant_key(entity_id)
        if tenant is None:
            return {
                "entity_id": None,
                "stamp_present": False,
                "signature_present": False,
                "warnings": ["missing_tenant"],
                "matches": {},
                "proof": False,
                "note": "No organization id was provided. Nothing was compared and nothing was saved.",
            }
        marks = find_marks(gray)
        warnings: list[str] = []
        matches: dict[str, dict] = {}
        expected = {"stamp": expect_stamp, "signature": expect_signature}
        for kind in KINDS:
            region = marks[kind]
            present = region is not None
            if expected[kind] and not present:
                warnings.append(f"missing_{kind}")
                matches[kind] = {
                    "status": "missing",
                    "similarity": None,
                    "specimen_id": None,
                    "differences": [],
                    "verdict": None,
                    "reason_codes": ["missing_stamp" if kind == "stamp" else "missing_signature"],
                    "review_reason": "missing_stamp" if kind == "stamp" else "missing_signature",
                    "evidence": {},
                }
                continue
            if not present:
                matches[kind] = {"status": "not_expected", "similarity": None, "specimen_id": None, "differences": []}
                continue
            judgment = self._judge(tenant, kind, gray, region)
            if judgment["specimen_id"] is None:
                matches[kind] = {
                    "status": "no_specimen",
                    "similarity": None,
                    "specimen_id": None,
                    "differences": [],
                    "verdict": None,
                    "genuine_probability": None,
                    "comment": None,
                    "proposal_id": None,
                    "question": None,
                    "review_reason": judgment.get("review_reason") or "insufficient_reference",
                    "reason_codes": list(judgment.get("reason_codes") or ["insufficient_reference"]),
                    "evidence": dict(judgment.get("evidence") or {}),
                }
                continue
            if judgment["verdict"] == "fraudulent":
                warnings.append(f"{kind}_fraudulent")
                matches[kind] = {
                    "status": "fraudulent",
                    "similarity": round(judgment["score"], 4),
                    "specimen_id": judgment["specimen_id"],
                    "differences": judgment["differences"],
                    "verdict": "fraudulent",
                    "genuine_probability": judgment["probability"],
                    "comment": judgment["comment"],
                    "proposal_id": None,
                    "question": None,
                    "read_text": judgment["read_text"],
                    "enrolled_text": judgment["enrolled_text"],
                    "alignment_ncc": judgment.get("alignment_ncc"),
                    "review_reason": judgment.get("review_reason"),
                    "reason_codes": list(judgment.get("reason_codes") or []),
                    "evidence": dict(judgment.get("evidence") or {}),
                }
                continue
            if judgment["verdict"] == "uncertain":
                warnings.append(f"{kind}_uncertain")
                matches[kind] = {
                    "status": "uncertain",
                    "similarity": round(judgment["score"], 4),
                    "specimen_id": judgment["specimen_id"],
                    "differences": judgment["differences"],
                    "verdict": "uncertain",
                    "genuine_probability": judgment["probability"],
                    "comment": judgment["comment"],
                    "proposal_id": None,
                    "question": _uncertain_question(kind),
                    "read_text": judgment["read_text"],
                    "enrolled_text": judgment["enrolled_text"],
                    "alignment_ncc": judgment.get("alignment_ncc"),
                    "review_reason": judgment.get("review_reason"),
                    "reason_codes": list(judgment.get("reason_codes") or []),
                    "evidence": dict(judgment.get("evidence") or {}),
                }
                continue
            if judgment["verdict"] != "genuine":
                warnings.append(f"{kind}_unrecognized")
                matches[kind] = {
                    "status": "unrecognized",
                    "similarity": round(judgment["score"], 4),
                    "specimen_id": judgment["specimen_id"],
                    "differences": judgment["differences"],
                    "verdict": "unrecognized",
                    "genuine_probability": judgment["probability"],
                    "comment": judgment["comment"],
                    "proposal_id": self._propose(tenant, kind, gray),
                    "question": _unrecognized_question(
                        kind, tenant, judgment["read_text"], judgment["enrolled_text"]
                    ),
                    "read_text": judgment["read_text"],
                    "enrolled_text": judgment["enrolled_text"],
                    "alignment_ncc": judgment.get("alignment_ncc"),
                    "review_reason": judgment.get("review_reason"),
                    "reason_codes": list(judgment.get("reason_codes") or []),
                    "evidence": dict(judgment.get("evidence") or {}),
                }
                continue
            matches[kind] = {
                "status": "match",
                "similarity": round(judgment["score"], 4),
                "specimen_id": judgment["specimen_id"],
                "differences": [],
                "verdict": "genuine",
                "genuine_probability": judgment["probability"],
                "comment": judgment["comment"],
                "proposal_id": None,
                "question": None,
                "read_text": judgment["read_text"],
                "enrolled_text": judgment["enrolled_text"],
                "alignment_ncc": judgment.get("alignment_ncc"),
                "review_reason": judgment.get("review_reason"),
                "reason_codes": list(judgment.get("reason_codes") or []),
                "evidence": dict(judgment.get("evidence") or {}),
            }
            matches[kind].update(review_triage(matches[kind].get("verdict"), matches[kind].get("reason_codes")))
        for match in matches.values():
            if "review_recommended" in match:
                continue
            status = match.get("status")
            verdict = "missing" if status == "missing" else match.get("verdict")
            match.update(review_triage(verdict, match.get("reason_codes")))
        return {
            "entity_id": tenant,
            "stamp_present": marks["stamp"] is not None,
            "signature_present": marks["signature"] is not None,
            "warnings": warnings,
            "matches": matches,
            "proof": False,
            "note": (
                "A close match to an enrolled stamp is genuine. A hole or a broken text-line "
                "profile on that stamp is fraudulent. A low alignment score alone is uncertain. "
                "A different drawing is unrecognized and can be enrolled. Approval stores the "
                "crop the user accepted. It does not prove the stamp is authentic. "
                "After the first approval, later requests for that organization must present "
                "the returned tenant secret. There is no login beyond that secret."
            ),
        }
