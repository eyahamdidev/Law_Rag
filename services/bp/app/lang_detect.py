"""Lightweight document language hint for uploads (French / English / Arabic)."""

from __future__ import annotations

from app.agents.common import fold

_FR = (" le ", " la ", " les ", " des ", " une ", " pour ", " avec ", " nous ", " est ", " du ", " sur ", " dans ")
_EN = (" the ", " and ", " for ", " with ", " we ", " our ", " is ", " are ", " of ", " to ", " this ", " that ")
_AR = (" من ", " في ", " على ", " هذا ", " التي ", " نحن ")


def detect_document_lang(text: str, default: str = "fr") -> str:
    sample = f" {fold(text[:16000])} "
    fr, en, ar = (sum(sample.count(w) for w in marks) for marks in (_FR, _EN, _AR))
    best = max((fr, "fr"), (en, "en"), (ar, "ar"), key=lambda x: x[0])
    if best[0] < 8:
        return default if default in ("fr", "en", "ar") else "fr"
    return best[1]
