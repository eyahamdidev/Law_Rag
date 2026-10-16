"""Page-level text extraction with PyMuPDF.

Three problems found while profiling the corpus are handled here:

1. Broken font encodings. The 2000 Companies Code JORT (Loi 2000-93) embeds a
   font whose glyph codes are shifted by 29 ("-RXUQDO" for "Journal") with a
   few accented letters remapped. Fonts are flagged per document when their
   spans contain control characters, and only those spans are decoded, because
   the same page mixes broken and normal fonts.
2. Arabic presentation forms. Arabic PDFs extract as isolated/initial/final
   glyph forms (U+FB50-U+FEFF). NFKC folds them back to base letters, which
   is what keyword search and the embedder expect.
3. Scanned pages. A page with almost no text is flagged `needs_ocr`. If an
   OCR result exists in data/ocr/<sha256>/<page>.txt it is used instead; the
   vision OCR job in `ocr.py` writes those files.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.config import settings

pymupdf.TOOLS.mupdf_display_errors(False)

SPARSE_PAGE_CHARS = 80

_SHIFT = 29
# Glyphs of the broken font that do not follow the +29 shift.
_BROKEN_FONT_EXTRA = {
    "p": "é", "j": "à", "q": "è", "r": "ê", "{": "ô", "k": "ë", "v": "î",
    "o": "ç", "w": "ï", "d": "Ç", "\x80": "û", "\x7f": "ù", "\x83": "°",
    "¶": "'", "«": ".", "±": "-", "²": "–", "©": "«", "ª": "»", "°": "œ",
}


@dataclass
class PageText:
    page: int  # 1-based, as printed in the PDF viewer
    text: str
    needs_ocr: bool
    source: str  # "text", "decoded_font" or "ocr"


def _decode_broken(text: str) -> str:
    out = []
    for char in text:
        code = ord(char)
        if char == "\x03":
            out.append(" ")
        elif char == " ":
            out.append(char)
        elif 0x04 <= code <= 0x5D:  # includes "\n", the font's apostrophe
            out.append(chr(code + _SHIFT))
        else:
            out.append(_BROKEN_FONT_EXTRA.get(char, char))
    return "".join(out)


def _broken_fonts(doc: pymupdf.Document, sample_pages: int = 6) -> set[str]:
    fonts: dict[str, list[int]] = {}
    for page in doc.pages(0, min(sample_pages, doc.page_count)):
        for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    text = span["text"]
                    if not text.strip():
                        continue
                    control = sum(1 for c in text if ord(c) < 0x20 and c not in "\n\t")
                    stats = fonts.setdefault(span["font"], [0, 0])
                    stats[0] += control
                    stats[1] += len(text)
    return {name for name, (control, total) in fonts.items() if total and control / total > 0.05}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("­", "")
    text = re.sub(r"\.{4,}|…{2,}", " ", text)  # table-of-contents leaders
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # hyphenated line breaks
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _page_text(page: pymupdf.Page, broken: set[str]) -> tuple[str, bool]:
    if not broken:
        return page.get_text("text", sort=False), False
    blocks = []
    decoded_any = False
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]:
        lines = []
        for line in block.get("lines", []):
            parts = []
            for span in line["spans"]:
                if span["font"] in broken:
                    parts.append(_decode_broken(span["text"]))
                    decoded_any = True
                else:
                    parts.append(span["text"])
            lines.append("".join(parts))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), decoded_any


# Article headings repeat once digits are masked. They are structure, not banners.
_KEEP_LINE = re.compile(r"^(article|art\.|chapitre|titre|section|الفصل|فصل|الباب|القسم)")


def _line_key(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def strip_running_headers(pages: list[PageText], min_share: float = 0.3) -> list[PageText]:
    """Drop lines that repeat on many pages, such as the JORT page banner.

    Digits are masked first so "Page 2746" and "Page 2747" count as one line.
    """
    with_text = [page for page in pages if page.text]
    if len(with_text) < 4:
        return pages
    counts: dict[str, int] = {}
    for page in with_text:
        for key in {_line_key(line) for line in page.text.splitlines() if line.strip()}:
            counts[key] = counts.get(key, 0) + 1
    threshold = max(3, int(len(with_text) * min_share))
    running = {
        key
        for key, count in counts.items()
        if count >= threshold and len(key) < 120 and not _KEEP_LINE.match(key)
    }
    if not running:
        return pages
    for page in with_text:
        lines = [line for line in page.text.splitlines() if _line_key(line) not in running]
        page.text = "\n".join(lines).strip()
    return pages


def ocr_cache_path(sha256: str, page: int) -> Path:
    return settings.data_dir / "ocr" / sha256 / f"{page:04d}.txt"


def extract_pages(path: Path, sha256: str) -> list[PageText]:
    pages: list[PageText] = []
    with pymupdf.open(path) as doc:
        broken = _broken_fonts(doc)
        for index, page in enumerate(doc, start=1):
            raw, decoded = _page_text(page, broken)
            text = normalize(raw)
            sparse = len(re.sub(r"\s", "", text)) < SPARSE_PAGE_CHARS
            # Arabic legacy fonts can yield hundreds of Latin/control glyphs.
            # Length alone must not make that corrupted layer searchable.
            controls = sum(ord(c) < 32 and c not in "\n\r\t" for c in text)
            replacements = text.count("\ufffd")
            arabic_expected = bool(re.search(r"(?:_|\d)ar(?:_|\.|$)", path.name.lower()))
            arabic_letters = sum("\u0600" <= c <= "\u06ff" for c in text)
            letters = sum(c.isalpha() for c in text)
            corrupted = (controls + replacements) / max(len(text), 1) > 0.01
            if arabic_expected and letters > 80 and arabic_letters / letters < 0.1:
                corrupted = True
            sparse = sparse or corrupted
            source = "decoded_font" if decoded else "text"
            if sparse:
                cached = ocr_cache_path(sha256, index)
                if cached.exists():
                    text = normalize(cached.read_text(encoding="utf-8"))
                    sparse = len(re.sub(r"\s", "", text)) < 40
                    source = "ocr"
                if sparse:
                    text = ""  # sparse/broken text is not legal evidence
            pages.append(PageText(page=index, text=text, needs_ocr=sparse, source=source))
    return strip_running_headers(pages)
