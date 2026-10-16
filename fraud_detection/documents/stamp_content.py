"""Read the words on a stamp and decide whether two stamps say the same thing.

A close copy of the same wording is judged genuine or fraudulent. A stamp whose
wording is about a different organization is not fraudulent. The caller asks
whether to enroll that different stamp.
"""

from __future__ import annotations

import re
import unicodedata

import numpy as np
from PIL import Image

# Words that appear on many specimen stamps and do not identify the organization.
_SHARED = {
    "pour",
    "par",
    "les",
    "des",
    "une",
    "dans",
    "the",
    "and",
    "est",
    "que",
    "sur",
    "aux",
    "avec",
    "pas",
    "specimen",
    "faux",
    "utiliser",
    "delegation",
    "fictif",
    "fictive",
    "comite",
    "cachet",
}


def read_stamp_text(image: np.ndarray) -> str:
    """Best-effort OCR. Empty when Tesseract is not installed or the crop has no words."""
    try:
        import pytesseract
    except ImportError:
        return ""
    array = np.asarray(image)
    if array.ndim == 2:
        picture = Image.fromarray(array, mode="L")
    else:
        picture = Image.fromarray(array[:, :, :3].astype(np.uint8), mode="RGB")
    best = ""
    for scale in (2, 3, 4):
        enlarged = picture.resize((picture.width * scale, picture.height * scale), Image.Resampling.LANCZOS)
        try:
            text = pytesseract.image_to_string(enlarged, lang="fra+eng", config="--psm 6")
        except Exception:
            try:
                text = pytesseract.image_to_string(enlarged, config="--psm 6")
            except Exception:
                return best
        text = " ".join(text.split())
        if len(_tokens(text)) >= 2:
            return text
        if len(text) > len(best):
            best = text
    return best


def _tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return {word for word in re.findall(r"[a-z0-9]{3,}", folded) if word not in _SHARED}


def content_relation(left: str, right: str) -> str:
    """Return same, different, or unknown.

    Unknown means the crops did not yield enough words to compare. Same means
    the smaller reading is mostly contained in the other. Different means each
    stamp names something else.
    """
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return "unknown"
    shared = left_tokens & right_tokens
    coverage = len(shared) / min(len(left_tokens), len(right_tokens))
    if coverage >= 0.45 and len(shared) >= 2:
        return "same"
    return "different"
