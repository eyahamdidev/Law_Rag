"""Supervised stamp check: one enrolled genuine crop versus a later crop.

Training uses labeled pairs. A pair is genuine when the later crop is the same
stamp (another copy, a scan, or light noise). A pair is fake when the later
crop is a counterfeit or a different stamp. The label is known for every pair,
so this is supervised learning. An unsupervised model would only look for
odd pixels and would not be taught which differences are forgeries.

The live store does not contain those training stamps. A user enrolls one
genuine crop, and this model judges the next document against that crop.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

_CANVAS = 96
_ANGLES = tuple(range(-16, 17, 4))
_SHIFTS = (-8, -4, 0, 4, 8)
_BLOCK = 8

FEATURE_NAMES: tuple[str, ...] = (
    "width_ratio",
    "height_ratio",
    "area_ratio",
    "aspect_gap",
    "density_gap",
    "best_ncc",
    "best_mae",
    "best_ink_cosine",
    "chroma_mae",
    "rgb_mae",
    "block_mean",
    "block_std",
    "block_max",
    "horiz_corr",
    "vert_corr",
    "radial_corr",
    "hist_corr",
    "edge_gap",
    "local_mean",
    "local_min",
    *[f"hu_{index}" for index in range(7)],
    *[f"block_{index}" for index in range(_BLOCK * _BLOCK)],
    *[f"local_{index}" for index in range(_BLOCK * _BLOCK)],
)


def _as_rgb(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim == 2:
        return np.stack([array, array, array], axis=-1).astype(np.uint8)
    if array.shape[-1] == 4:
        array = array[:, :, :3]
    return array.astype(np.uint8)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    channels = rgb.astype(np.float32)
    return 0.299 * channels[:, :, 0] + 0.587 * channels[:, :, 1] + 0.114 * channels[:, :, 2]


def _foreground(lum: np.ndarray) -> np.ndarray:
    bright = float(np.percentile(lum, 92))
    dark = float(np.percentile(lum, 8))
    if bright - dark < 25:
        return lum < 160
    return lum < (bright + dark) / 2.0


def _shift(image: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.full_like(image, 255)
    height, width = image.shape[:2]
    y0, y1 = max(0, dy), min(height, height + dy)
    x0, x1 = max(0, dx), min(width, width + dx)
    sy0, sy1 = max(0, -dy), min(height, height - dy)
    sx0, sx1 = max(0, -dx), min(width, width - dx)
    out[y0:y1, x0:x1] = image[sy0:sy1, sx0:sx1]
    return out


def _rotate(image: np.ndarray, degrees: float) -> np.ndarray:
    if degrees == 0:
        return image
    rotated = Image.fromarray(image, mode="RGB").rotate(
        degrees,
        resample=Image.Resampling.BILINEAR,
        fillcolor=(255, 255, 255),
    )
    return np.asarray(rotated, dtype=np.uint8)


def _hu(binary: np.ndarray) -> np.ndarray:
    height, width = binary.shape
    yy, xx = np.mgrid[0:height, 0:width]
    weights = binary.astype(np.float64)
    m00 = float(weights.sum()) + 1e-8
    cx = float((xx * weights).sum()) / m00
    cy = float((yy * weights).sum()) / m00
    x = xx - cx
    y = yy - cy
    mu20 = float((x**2 * weights).sum())
    mu02 = float((y**2 * weights).sum())
    mu11 = float((x * y * weights).sum())
    mu30 = float((x**3 * weights).sum())
    mu03 = float((y**3 * weights).sum())
    mu12 = float((x * (y**2) * weights).sum())
    mu21 = float(((x**2) * y * weights).sum())
    n20, n02, n11 = mu20 / m00**2, mu02 / m00**2, mu11 / m00**2
    n30, n03 = mu30 / m00**2.5, mu03 / m00**2.5
    n12, n21 = mu12 / m00**2.5, mu21 / m00**2.5
    h1 = n20 + n02
    h2 = (n20 - n02) ** 2 + 4 * n11**2
    h3 = (n30 - 3 * n12) ** 2 + (3 * n21 - n03) ** 2
    h4 = (n30 + n12) ** 2 + (n21 + n03) ** 2
    h5 = (n30 - 3 * n12) * (n30 + n12) * ((n30 + n12) ** 2 - 3 * (n21 + n03) ** 2) + (3 * n21 - n03) * (
        n21 + n03
    ) * (3 * (n30 + n12) ** 2 - (n21 + n03) ** 2)
    h6 = (n20 - n02) * ((n30 + n12) ** 2 - (n21 + n03) ** 2) + 4 * n11 * (n30 + n12) * (n21 + n03)
    h7 = (3 * n21 - n03) * (n30 + n12) * ((n30 + n12) ** 2 - 3 * (n21 + n03) ** 2) - (n30 - 3 * n12) * (
        n21 + n03
    ) * (3 * (n30 + n12) ** 2 - (n21 + n03) ** 2)
    raw = np.array([h1, h2, h3, h4, h5, h6, h7], dtype=np.float64)
    return np.sign(raw) * np.log1p(np.abs(raw))


def _radial(binary: np.ndarray) -> np.ndarray:
    height, width = binary.shape
    yy, xx = np.mgrid[0:height, 0:width]
    radius = np.sqrt((yy - (height - 1) / 2) ** 2 + (xx - (width - 1) / 2) ** 2)
    radius = radius / (float(radius.max()) + 1e-6)
    profile = np.zeros(8, dtype=np.float32)
    edges = np.linspace(0, 1, 9)
    flat = binary.astype(np.float32)
    for index in range(8):
        upper = radius <= edges[index + 1] if index == 7 else radius < edges[index + 1]
        selected = (radius >= edges[index]) & upper
        if selected.any():
            profile[index] = float(flat[selected].mean())
    return profile


def _histogram(lum: np.ndarray) -> np.ndarray:
    counts, _ = np.histogram(lum, bins=16, range=(0, 255))
    counts = counts.astype(np.float32)
    total = float(counts.sum()) + 1e-6
    return counts / total


def _edge_energy(lum: np.ndarray) -> float:
    gy = np.abs(np.diff(lum.astype(np.float32), axis=0)).mean()
    gx = np.abs(np.diff(lum.astype(np.float32), axis=1)).mean()
    return float(gx + gy)


def _corr(left: np.ndarray, right: np.ndarray) -> float:
    a = left.astype(np.float32).reshape(-1)
    b = right.astype(np.float32).reshape(-1)
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-6:
        return 0.0
    return float(np.dot(a, b) / denom)


@dataclass
class PreparedStamp:
    width: int
    height: int
    area: int
    aspect: float
    density: float
    canvas: np.ndarray
    rotations: dict[int, np.ndarray]
    histogram: np.ndarray
    hu: np.ndarray
    edge: float
    ink: int


def _ink_mask(rgb: np.ndarray) -> np.ndarray:
    """Prefer colored stamp ink so nearby black text is not part of the crop."""
    red = rgb[:, :, 0].astype(np.int16)
    green = rgb[:, :, 1].astype(np.int16)
    blue = rgb[:, :, 2].astype(np.int16)
    chroma = np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue)
    lum = _luminance(rgb)
    colored = (chroma >= 24) & (lum < 245)
    if int(colored.sum()) >= 40:
        return colored
    return _foreground(lum)


def prepare_stamp(image: np.ndarray) -> PreparedStamp | None:
    rgb = _as_rgb(image)
    lum = _luminance(rgb)
    mask = _ink_mask(rgb)
    if int(mask.sum()) < 15:
        return None
    ys, xs = np.nonzero(mask)
    crop = rgb[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    height, width = crop.shape[:2]
    area = int(mask.sum())
    canvas = np.asarray(Image.fromarray(crop, mode="RGB").resize((_CANVAS, _CANVAS), Image.Resampling.BILINEAR), dtype=np.uint8)
    canvas_lum = _luminance(canvas)
    binary = _foreground(canvas_lum)
    rotations = {angle: canvas if angle == 0 else _rotate(canvas, angle) for angle in _ANGLES}
    return PreparedStamp(
        width=int(width),
        height=int(height),
        area=area,
        aspect=width / max(1, height),
        density=area / max(1, width * height),
        canvas=canvas,
        rotations=rotations,
        histogram=_histogram(canvas_lum),
        hu=_hu(binary),
        edge=_edge_energy(canvas_lum),
        ink=area,
    )


def _ncc(left: np.ndarray, right: np.ndarray) -> float:
    a = left - left.mean()
    b = right - right.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-6:
        return 0.0
    return float(np.dot(a.reshape(-1), b.reshape(-1)) / denom)


def pair_features(enrolled: PreparedStamp, query: PreparedStamp) -> np.ndarray:
    """Differences between the enrolled genuine crop and one later crop."""
    base = _luminance(enrolled.canvas)
    best_ncc = -2.0
    best_query = query.canvas
    for angle in _ANGLES:
        rotated = query.rotations.get(angle)
        if rotated is None:
            rotated = _rotate(query.canvas, angle)
        for dy in _SHIFTS:
            for dx in _SHIFTS:
                shifted = rotated if dy == 0 and dx == 0 else _shift(rotated, dy, dx)
                score = _ncc(base, _luminance(shifted))
                if score > best_ncc:
                    best_ncc = score
                    best_query = shifted
    left_lum = base
    right_lum = _luminance(best_query)
    diff = np.abs(left_lum - right_lum)
    block = diff.reshape(_BLOCK, _CANVAS // _BLOCK, _BLOCK, _CANVAS // _BLOCK).mean(axis=(1, 3)).reshape(-1)
    step = _CANVAS // _BLOCK
    local = np.empty(_BLOCK * _BLOCK, dtype=np.float32)
    cursor = 0
    for row in range(_BLOCK):
        for col in range(_BLOCK):
            local[cursor] = _corr(
                left_lum[row * step : (row + 1) * step, col * step : (col + 1) * step],
                right_lum[row * step : (row + 1) * step, col * step : (col + 1) * step],
            )
            cursor += 1
    left_ink = _foreground(left_lum).astype(np.float32).reshape(-1)
    right_ink = _foreground(right_lum).astype(np.float32).reshape(-1)
    left_norm = float(np.linalg.norm(left_ink)) + 1e-6
    right_norm = float(np.linalg.norm(right_ink)) + 1e-6
    ink_cosine = float(np.dot(left_ink, right_ink) / (left_norm * right_norm))
    left_chroma = enrolled.canvas.max(axis=2).astype(np.float32) - enrolled.canvas.min(axis=2).astype(np.float32)
    right_chroma = best_query.max(axis=2).astype(np.float32) - best_query.min(axis=2).astype(np.float32)
    summary = np.array(
        [
            query.width / max(1, enrolled.width),
            query.height / max(1, enrolled.height),
            query.area / max(1, enrolled.area),
            abs(query.aspect - enrolled.aspect),
            abs(query.density - enrolled.density),
            best_ncc,
            float(diff.mean()) / 255.0,
            ink_cosine,
            float(np.abs(left_chroma - right_chroma).mean()) / 255.0,
            float(np.abs(enrolled.canvas.astype(np.float32) - best_query.astype(np.float32)).mean()) / 255.0,
            float(block.mean()) / 255.0,
            float(block.std()) / 255.0,
            float(block.max()) / 255.0,
            _corr(left_lum.mean(axis=1), right_lum.mean(axis=1)),
            _corr(left_lum.mean(axis=0), right_lum.mean(axis=0)),
            _corr(_radial(_foreground(left_lum)), _radial(_foreground(right_lum))),
            _corr(enrolled.histogram, _histogram(right_lum)),
            abs(query.edge - enrolled.edge) / (enrolled.edge + 1e-6),
            float(local.mean()),
            float(local.min()),
        ],
        dtype=np.float32,
    )
    hu_gap = np.abs(enrolled.hu - query.hu).astype(np.float32)
    return np.concatenate([summary, hu_gap, (block / 255.0).astype(np.float32), local])


class StampVerifier:
    """Labeled genuine-versus-fake comparator. Not an anomaly detector."""

    def __init__(self):
        self.model = None
        self.backend = "untrained"
        self.threshold = 0.5
        self.feature_names = FEATURE_NAMES
        self.method = "supervised"

    def fit(self, features: np.ndarray, labels: np.ndarray, threshold: float = 0.5) -> "StampVerifier":
        if len(set(labels.tolist())) < 2:
            raise ValueError("supervised stamp training needs both genuine and fake pairs")
        try:
            import lightgbm as lgb

            model = lgb.LGBMClassifier(
                n_estimators=240,
                learning_rate=0.05,
                num_leaves=31,
                min_child_samples=15,
                subsample=0.9,
                colsample_bytree=0.85,
                class_weight="balanced",
                random_state=0,
                verbosity=-1,
            )
            model.fit(features, labels)
            self.backend = "lightgbm"
        except Exception:
            from sklearn.ensemble import HistGradientBoostingClassifier

            model = HistGradientBoostingClassifier(
                max_iter=240,
                learning_rate=0.06,
                max_leaf_nodes=31,
                random_state=0,
                class_weight="balanced",
            )
            model.fit(features, labels)
            self.backend = "hist_gradient_boosting"
        self.model = model
        self.threshold = float(threshold)
        return self

    def compare(self, enrolled: np.ndarray, query: np.ndarray) -> dict | None:
        """Probability plus how tightly the later crop lines up with the saved one."""
        if self.model is None:
            return None
        left = prepare_stamp(enrolled)
        right = prepare_stamp(query)
        if left is None or right is None:
            probability = 0.0
            width_ratio = height_ratio = best_ncc = 0.0
        else:
            features = pair_features(left, right)
            probability = float(self.model.predict_proba(features.reshape(1, -1))[0, 1])
            width_ratio, height_ratio, best_ncc = float(features[0]), float(features[1]), float(features[5])
        exact = 0.97 <= width_ratio <= 1.03 and 0.97 <= height_ratio <= 1.03 and best_ncc >= 0.97
        if exact:
            probability = max(probability, 0.99)
        return {
            "genuine_probability": probability,
            "width_ratio": width_ratio,
            "height_ratio": height_ratio,
            "ncc": best_ncc,
            "exact": exact,
        }

    def genuine_probability(self, enrolled: np.ndarray, query: np.ndarray) -> float | None:
        compared = self.compare(enrolled, query)
        if compared is None:
            return None
        return compared["genuine_probability"]

    def judge(self, enrolled: np.ndarray, query: np.ndarray) -> dict:
        compared = self.compare(enrolled, query)
        if compared is None:
            return {
                "genuine": None,
                "genuine_probability": None,
                "verdict": None,
                "threshold": self.threshold,
                "method": self.method,
                "ncc": None,
                "exact": False,
                "width_ratio": None,
                "height_ratio": None,
            }
        probability = compared["genuine_probability"]
        genuine = probability >= self.threshold
        return {
            "genuine": genuine,
            "genuine_probability": round(probability, 4),
            "verdict": "genuine" if genuine else "fake",
            "threshold": self.threshold,
            "method": self.method,
            "ncc": round(compared["ncc"], 4),
            "exact": compared["exact"],
            "width_ratio": round(compared["width_ratio"], 4),
            "height_ratio": round(compared["height_ratio"], 4),
        }

    def save(self, path) -> None:
        import joblib

        joblib.dump(
            {
                "model": self.model,
                "backend": self.backend,
                "threshold": self.threshold,
                "feature_names": self.feature_names,
                "method": self.method,
            },
            path,
        )

    @classmethod
    def load(cls, path) -> "StampVerifier":
        import joblib

        payload = joblib.load(path)
        verifier = cls()
        verifier.model = payload["model"]
        verifier.backend = payload.get("backend", "lightgbm")
        verifier.threshold = float(payload.get("threshold", 0.5))
        verifier.feature_names = tuple(payload.get("feature_names") or FEATURE_NAMES)
        verifier.method = payload.get("method", "supervised")
        return verifier


def encode_png(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    array = _as_rgb(image)
    Image.fromarray(array, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()
