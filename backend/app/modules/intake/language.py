"""Language guess used until a dedicated detector is calibrated.

Arabic script maps to ar. A few frequent French function words map to fr.
Everything else stays en. This is a routing hint, not a language-ID evaluation.
"""

_FRENCH_MARKERS = (
    " le ",
    " la ",
    " les ",
    " des ",
    " une ",
    " est ",
    " que ",
    " pour ",
    " dans ",
    " société ",
    " societe ",
    " comment ",
    " quelles ",
)


def detect_language(text: str) -> str:
    if any("\u0600" <= char <= "\u06ff" for char in text):
        return "ar"
    padded = f" {text.lower()} "
    if any(marker in padded for marker in _FRENCH_MARKERS):
        return "fr"
    return "en"
