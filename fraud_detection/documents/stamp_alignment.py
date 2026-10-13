"""Align two stamp crops and measure whether the drawing is the same one.

The check is scale-invariant and contrast-invariant. It undoes a small rotation,
then compares the ink. A high score means the lines, letters, and borders land
on top of each other. It does not decide genuine or fraudulent by itself.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

_SIDE = 192
# Even steps, wide enough for a 12° page turn. Odd degrees are checked only
# next to the winner, after the shift search, because a small turn often
# looks worse until the crop is nudged.
_ANGLES = tuple(range(-14, 15, 2))
# An 8×8 patch of the aligned drawing. Measured on the four enrolled PDFs:
# a brightness or JPEG change stays under 20 when the drawing already lines
# up (score at least 0.97). A hole that removes ink on the balance and
# labellisation stamps peaks at 118 or more. 40 sits in that gap. It was not
# fit on the labeled pages.
_PATCH = 8
_HOLE_PEAK = 40.0
_HOLE_STRONG = 100.0
# Harmless edits of the enrolled crop (a 6° turn, a blur) keep the horizontal
# ink profile within this margin of the weakest of those edits. The margin
# sits below every genuine reference page of the four enrolled PDFs and was
# not chosen to maximize counterfeit recall. A low global score alone is not
# enough: the text lines themselves have to miss.
_ROW_MARGIN = 0.09


def _rgb(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim == 2:
        return np.stack([array, array, array], axis=-1).astype(np.uint8)
    return array[:, :, :3].astype(np.uint8)


def _gray(rgb: np.ndarray) -> np.ndarray:
    channels = rgb.astype(np.float32)
    return 0.299 * channels[:, :, 0] + 0.587 * channels[:, :, 1] + 0.114 * channels[:, :, 2]


def _paper(gray: np.ndarray) -> float:
    """Background level. A tinted field is not treated as ink, and white padding from a rotation is not treated as the only paper."""
    bright = float((gray >= 245).mean())
    if bright < 0.45:
        interior = gray[gray < 245]
        if interior.size > 0.35 * gray.size:
            low = float(np.percentile(interior, 75))
            high = float(np.percentile(interior, 95))
            if high - low < 18:
                return low
    return float(np.percentile(gray, 90))


def _whiten(rgb: np.ndarray) -> np.ndarray:
    """Lift the paper to white so a darker scan can be compared with the reference."""
    gray = _gray(rgb)
    paper = _paper(gray)
    if paper < 40 or paper > 250:
        return rgb
    lifted = np.clip(rgb.astype(np.float32) * (255.0 / paper), 0, 255)
    return lifted.astype(np.uint8)


def _tight(rgb: np.ndarray) -> np.ndarray:
    """Keep the ink. Paper is lifted to white first so a dark scan still crops."""
    rgb = _whiten(_rgb(rgb))
    gray = _gray(rgb)
    paper = _paper(gray)
    mask = gray < (paper - 22)
    if int(mask.sum()) < 25 or float(mask.mean()) > 0.72:
        return rgb
    ys, xs = np.nonzero(mask)
    box_h = int(ys.max() - ys.min() + 1)
    box_w = int(xs.max() - xs.min() + 1)
    pad_y = max(2, int(0.03 * box_h))
    pad_x = max(2, int(0.03 * box_w))
    y0 = max(0, int(ys.min()) - pad_y)
    y1 = min(rgb.shape[0], int(ys.max()) + 1 + pad_y)
    x0 = max(0, int(xs.min()) - pad_x)
    x1 = min(rgb.shape[1], int(xs.max()) + 1 + pad_x)
    return rgb[y0:y1, x0:x1]


def _square(rgb: np.ndarray) -> np.ndarray:
    rgb = _rgb(rgb)
    height, width = rgb.shape[:2]
    side = max(height, width, 8)
    canvas = np.full((side, side, 3), 255, np.uint8)
    top = (side - height) // 2
    left = (side - width) // 2
    canvas[top : top + height, left : left + width] = rgb
    resized = Image.fromarray(canvas, mode="RGB").resize((_SIDE, _SIDE), Image.Resampling.BICUBIC)
    return np.asarray(resized, dtype=np.uint8)


def _stretch(gray: np.ndarray) -> np.ndarray:
    low, high = np.percentile(gray, [3, 97])
    if high - low < 6:
        return gray
    return np.clip((gray - low) * (255.0 / (high - low)), 0, 255).astype(np.float32)


def _rotate(rgb: np.ndarray, degrees: float) -> np.ndarray:
    if abs(degrees) < 0.05:
        return _rgb(rgb)
    rotated = Image.fromarray(_rgb(rgb), mode="RGB").rotate(
        degrees,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=(255, 255, 255),
    )
    return np.asarray(rotated, dtype=np.uint8)


def _ncc(left: np.ndarray, right: np.ndarray) -> float:
    a = left.astype(np.float32).ravel()
    b = right.astype(np.float32).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-6:
        return 0.0
    return float(np.dot(a, b) / denom)


def _prepare(rgb: np.ndarray, degrees: float) -> np.ndarray | None:
    crop = _tight(_rotate(rgb, degrees))
    if crop.size == 0 or min(crop.shape[:2]) < 8:
        return None
    return _stretch(_gray(_square(crop)))


def _placed(gray: np.ndarray, scale: float, dy: int, dx: int) -> np.ndarray | None:
    """Zoom and nudge a prepared stamp. A small residual scale is what a rotated crop leaves behind."""
    side = int(round(_SIDE * scale))
    if side < 8:
        return None
    resized = np.asarray(
        Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8)).resize(
            (side, side), Image.Resampling.BILINEAR
        ),
        dtype=np.float32,
    )
    if side >= _SIDE:
        top = (side - _SIDE) // 2 - dy
        left = (side - _SIDE) // 2 - dx
        if top < 0 or left < 0 or top + _SIDE > side or left + _SIDE > side:
            return None
        return resized[top : top + _SIDE, left : left + _SIDE]
    canvas = np.full((_SIDE, _SIDE), 255, np.float32)
    top = (_SIDE - side) // 2 + dy
    left = (_SIDE - side) // 2 + dx
    if top < 0 or left < 0 or top + side > _SIDE or left + side > _SIDE:
        return None
    canvas[top : top + side, left : left + side] = resized
    return canvas


def _refine(reference: np.ndarray, view: np.ndarray) -> tuple[float, np.ndarray]:
    best_score = _ncc(reference, view)
    best_view = view
    for scale in (0.96, 1.0, 1.04, 1.08):
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                placed = _placed(view, scale, dy, dx)
                if placed is None:
                    continue
                score = _ncc(reference, placed)
                if score > best_score:
                    best_score = score
                    best_view = placed
    return best_score, best_view


def _local_min(left: np.ndarray, right: np.ndarray, cells: int = 6) -> float:
    step = left.shape[0] // cells
    scores: list[float] = []
    for row in range(cells):
        for col in range(cells):
            block_left = left[row * step : (row + 1) * step, col * step : (col + 1) * step]
            block_right = right[row * step : (row + 1) * step, col * step : (col + 1) * step]
            if float(block_left.std()) < 4 and float(block_right.std()) < 4:
                continue
            scores.append(_ncc(block_left, block_right))
    if not scores:
        return 1.0
    return float(min(scores))


def _patch_peak(delta: np.ndarray) -> float:
    """Largest 8×8 average. A hole lifts one patch; scan noise does not."""
    kernel = np.ones((_PATCH, _PATCH), np.float32) / float(_PATCH * _PATCH)
    smoothed = ndimage.convolve(delta, kernel, mode="constant", cval=0.0)
    return float(smoothed.max()) if smoothed.size else 0.0


def _ink_peaks(reference: np.ndarray, aligned: np.ndarray) -> tuple[float, float]:
    """How much one aligned patch is brighter, and how much one is darker.

    Brighter means ink in the enrolled stamp is missing from the query.
    Darker means extra ink. A real hole is one-sided. A missed rotation
    moves ink both ways.
    """
    delta = aligned.astype(np.float32) - reference.astype(np.float32)
    bright = _patch_peak(np.clip(delta, 0, None))
    dark = _patch_peak(np.clip(-delta, 0, None))
    return bright, dark


def _row_corr(left: np.ndarray, right: np.ndarray) -> float:
    """Agreement of the horizontal ink profile. A moved line breaks it. Blur does not."""

    def profile(gray: np.ndarray) -> np.ndarray:
        ink = gray < (float(np.percentile(gray, 90)) - 18)
        return ink.mean(axis=1).astype(np.float32)

    return _ncc(profile(left), profile(right))


def _low_block(left: np.ndarray, right: np.ndarray, cells: int = 6) -> tuple[float, float, str | None, list]:
    """Share of weak blocks, the weakest informative block, and where it sits.

    Empty blocks are ignored in the share and recorded as null in the map.
    The weakest block is 1 when every informative block matches, and low when
    one patch of the drawing does not land. The map is the spatial difference
    after alignment. It is evidence for a reviewer, not a fraud probability.
    """
    step = left.shape[0] // cells
    informative = 0
    low = 0
    worst = 1.0
    worst_cell = None
    block_map: list[float | None] = []
    for row in range(cells):
        for col in range(cells):
            block_left = left[row * step : (row + 1) * step, col * step : (col + 1) * step]
            block_right = right[row * step : (row + 1) * step, col * step : (col + 1) * step]
            if float(block_left.std()) < 4 and float(block_right.std()) < 4:
                block_map.append(None)
                continue
            informative += 1
            score = _ncc(block_left, block_right)
            block_map.append(round(float(score), 3))
            if score < worst:
                worst = score
                worst_cell = f"{row},{col}"
            if score < 0.55:
                low += 1
    if informative == 0:
        return 0.0, 1.0, None, block_map
    return float(low / informative), float(worst), worst_cell, block_map


def _consider(
    reference: np.ndarray,
    query: np.ndarray,
    degrees: int,
    best_score: float,
    best_angle: int,
    best_view: np.ndarray | None,
) -> tuple[float, int, np.ndarray | None]:
    view = _prepare(query, degrees)
    if view is None:
        return best_score, best_angle, best_view
    refined, refined_view = _refine(reference, view)
    if refined > best_score:
        return refined, degrees, refined_view
    return best_score, best_angle, best_view


def compare_drawings(enrolled: np.ndarray, query: np.ndarray) -> dict:
    """Return how tightly the query drawing matches the enrolled drawing.

    ``ncc`` is 1 when the aligned ink is the same picture. ``local_min`` is the
    weakest block. ``bright_peak`` is the strongest patch of missing ink after
    that alignment. ``quality`` is ``failed`` when the crop has no usable ink.
    """
    empty = {
        "ncc": 0.0,
        "local_min": 0.0,
        "angle": 0,
        "quality": "failed",
        "bright_peak": 0.0,
        "dark_peak": 0.0,
        "mae": None,
        "row_corr": None,
        "low_block": None,
        "worst_block": None,
        "worst_cell": None,
        "block_map": None,
    }
    try:
        left = _prepare(enrolled, 0)
    except Exception:
        return empty
    if left is None:
        return empty
    best_score = -2.0
    best_angle = 0
    best_view: np.ndarray | None = None
    # Score the shift search at every angle. The unshifted score at the true
    # angle can be worse than a wrong angle, so keeping only the raw winner
    # drops a 2° turn.
    for degrees in _ANGLES:
        best_score, best_angle, best_view = _consider(
            left, query, degrees, best_score, best_angle, best_view
        )
    if best_view is None:
        return empty
    for degrees in (best_angle - 1, best_angle + 1):
        if degrees < -14 or degrees > 14 or degrees in _ANGLES:
            continue
        best_score, best_angle, best_view = _consider(
            left, query, degrees, best_score, best_angle, best_view
        )
    local = _local_min(left, best_view)
    bright, dark = _ink_peaks(left, best_view)
    mae = float(np.mean(np.abs(left.astype(np.float32) - best_view.astype(np.float32))))
    row_corr = _row_corr(left, best_view)
    low_block, worst_block, worst_cell, block_map = _low_block(left, best_view)
    quality = "ok"
    # A strongly negative block means the lines did not land on each other.
    # That is a failed alignment, not proof the drawing was forged.
    if best_score < 0.2 or local < -0.15:
        quality = "poor"
    return {
        "ncc": round(float(best_score), 4),
        "local_min": round(float(local), 4),
        "angle": int(best_angle),
        "quality": quality,
        "bright_peak": round(float(bright), 1),
        "dark_peak": round(float(dark), 1),
        "mae": round(mae, 3),
        "row_corr": round(float(row_corr), 4),
        "low_block": round(float(low_block), 3),
        "worst_block": round(float(worst_block), 4),
        "worst_cell": worst_cell,
        "block_map": block_map,
    }


def harmless_row_floor(crop: np.ndarray) -> float | None:
    """Text-line agreement a harmless recapture of this crop still reaches.

    The floor is the weakest of a 6° turn and a small blur, minus a fixed
    margin. It is a property of the enrolled stamp, not of the labeled pages.
    """
    image = Image.fromarray(_rgb(crop), mode="RGB")
    edits = (
        image.rotate(6, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255)),
        image.rotate(-6, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255)),
        image.filter(ImageFilter.GaussianBlur(1.2)),
    )
    scores: list[float] = []
    reference = _rgb(crop)
    for edit in edits:
        result = compare_drawings(reference, np.asarray(edit, dtype=np.uint8))
        row_corr = result.get("row_corr")
        if result.get("quality") == "failed" or row_corr is None:
            continue
        scores.append(float(row_corr))
    if not scores:
        return None
    return round(min(scores) - _ROW_MARGIN, 4)


def _missing_ink(alignment: dict) -> str | None:
    """A compact hole on a drawing that otherwise lined up.

    ``strong`` is a large missing patch. ``present`` is smaller, enough to
    refuse a genuine verdict and not enough to call the stamp forged.
    """
    ncc = float(alignment.get("ncc") or 0.0)
    bright = float(alignment.get("bright_peak") or 0.0)
    dark = float(alignment.get("dark_peak") or 0.0)
    if ncc < 0.97 or bright < _HOLE_PEAK:
        return None
    # Both directions means the crop slid, not that ink was removed.
    if bright < 2.0 * max(dark, 1.0):
        return None
    if bright >= _HOLE_STRONG:
        return "strong"
    return "present"


# Laplacian variance of the capital PDF crop is about 4300. A 1.2 px blur
# falls to about 150 and a 2 px blur to about 23. Labeled scans of the four
# families stay above 1500. 40 is in that gap. A shorter side under 48 px is
# a sliver, not a stamp that can be compared.
_MIN_CROP_SIDE = 48
_BLUR_VARIANCE = 40.0


def crop_quality(crop: np.ndarray) -> str:
    """``unusable`` when blur or clipping leaves nothing safe to judge.

    An unusable crop is uncertain. It is not a new organization and it is
    not evidence of forgery.
    """
    rgb = _rgb(crop)
    if min(int(rgb.shape[0]), int(rgb.shape[1])) < _MIN_CROP_SIDE:
        return "unusable"
    gray = _gray(rgb)
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    variance = float(ndimage.convolve(gray, kernel, mode="nearest").var())
    if variance < _BLUR_VARIANCE:
        return "unusable"
    return "ok"


def stamp_decision(
    content: str,
    alignment: dict,
    probability: float | None,
    model_exact: bool,
) -> dict:
    """Verdict plus the reason codes for the branch that actually fired.

    ``probability`` and ``model_exact`` are accepted so older callers keep
    working. They do not change the verdict. Leave-one-document-out on the
    four training identities does not support using that score as proof.
    """
    _ = (probability, model_exact)
    if alignment.get("quality") == "failed":
        return {"verdict": "uncertain", "reason_codes": ["poor_image_quality"]}
    ncc = float(alignment.get("ncc") or 0.0)
    local = float(alignment.get("local_min") or 0.0)
    # Foreign stamps in the stress set stay under 0.23. The same stamp with
    # noisy OCR, including the round labellisation scans, still lands above
    # 0.50. A JPEG copy can scramble words while the pose also fails. That
    # conflict is uncertain, not a new stamp to enroll.
    if content == "unknown" and ncc < 0.50:
        return {"verdict": "unrecognized", "reason_codes": ["no_matching_enrolled_identity"]}
    if content == "different" and ncc < 0.50 and alignment.get("quality") != "poor":
        return {"verdict": "unrecognized", "reason_codes": ["no_matching_enrolled_identity"]}
    if content == "different" and ncc < 0.20:
        return {"verdict": "unrecognized", "reason_codes": ["no_matching_enrolled_identity"]}
    if alignment.get("quality") == "poor":
        return {"verdict": "uncertain", "reason_codes": ["poor_image_quality"]}
    missing = _missing_ink(alignment)
    if missing == "strong" and content == "same":
        return {"verdict": "fraudulent", "reason_codes": ["local_ink_anomaly"]}
    if missing is not None:
        return {"verdict": "uncertain", "reason_codes": ["local_ink_anomaly"]}
    row_corr = alignment.get("row_corr")
    row_floor = alignment.get("row_floor")
    if (
        content == "same"
        and row_corr is not None
        and row_floor is not None
        and float(row_corr) < float(row_floor)
        and 0.30 <= ncc < 0.82
        and local >= -0.18
    ):
        return {"verdict": "fraudulent", "reason_codes": ["local_ink_anomaly"]}
    mae = alignment.get("mae")
    low_block = alignment.get("low_block")
    close_scan = (
        row_corr is not None
        and float(row_corr) >= 0.97
        and ncc >= 0.955
        and local >= 0.50
        and mae is not None
        and float(mae) <= 8.0
        and (low_block is None or float(low_block) <= 0.02)
    )
    if close_scan or (ncc >= 0.992 and local >= 0.90):
        return {"verdict": "genuine", "reason_codes": ["reference_match"]}
    if content == "different":
        return {"verdict": "uncertain", "reason_codes": ["text_mismatch"]}
    return {"verdict": "uncertain", "reason_codes": ["insufficient_evidence"]}


def review_triage(verdict: str | None, reason_codes: list[str] | None) -> dict:
    """Review priority for one verdict. This is not a fraud probability.

    ``high`` means a person should look before anyone relies on the document.
    It is not an automatic rejection. A specific ink anomaly, a fraudulent
    verdict, or a PDF image-object clue is high. Everything else that is not
    a close match is still queued, at medium.

    OCR disagreement is medium on purpose. On the labeled labellisation pages
    the same ``text_mismatch`` code appears for genuine scans and for generated
    counterfeits, so it does not rank a case above ordinary uncertainty.
    """
    codes = set(reason_codes or [])
    if verdict == "genuine":
        return {"review_recommended": False, "risk_level": "low"}
    if verdict == "fraudulent" or "local_ink_anomaly" in codes or "possible_inserted_image" in codes:
        return {"review_recommended": True, "risk_level": "high"}
    return {"review_recommended": True, "risk_level": "medium"}


def stamp_verdict(
    content: str,
    alignment: dict,
    probability: float | None,
    model_exact: bool,
) -> str:
    """Turn wording plus the aligned drawing into one verdict.

    A near-perfect aligned drawing is genuine. A hole in that drawing is not.
    A low alignment score is uncertain: failing to line a stamp up is not
    evidence it was forged. Fraud requires the same wording and a text-line
    profile worse than a harmless recapture of the enrolled stamp, or a
    strong one-sided hole. A different wording is unrecognized when the
    drawing does not match either. A model score is not used.
    """
    return str(stamp_decision(content, alignment, probability, model_exact)["verdict"])
