"""Two chunking strategies, compared in eval/retrieval_eval.py.

fixed       Baseline from the deck. 1000-character windows with 150 characters
            of overlap, cut on whitespace, blind to document structure.
structural  Article-aware. Legal texts are cut at article headings
            ("Article 4.-", "Art. 12 :", "الفصل 3") so a passage is one article,
            which is also the unit a citation names. A JORT issue can carry
            several texts, so the current act ("Décret gouvernemental n°
            2017-389") is tracked and stored with each article. Articles longer
            than MAX_CHARS are split into linked parts that repeat the act and
            article in a header. Documents without article structure (guides,
            FAQs, programme pages) are split recursively on paragraphs, then
            lines, then sentences.

Character budgets, not tokens: multilingual-e5-large reads 512 tokens, and
1500 French characters is roughly 400 tokens, so a chunk plus its header fits.
"""

import bisect
import re
import uuid
from dataclasses import asdict, dataclass

from app.modules.intake.language import detect_language
from app.modules.rag.ingestion.extract import PageText
from app.modules.rag.ingestion.sources import SourceDocument

FIXED_SIZE = 1000
FIXED_OVERLAP = 150
MAX_CHARS = 1500
TARGET_CHARS = 1100
OVERLAP_CHARS = 200
MIN_ARTICLES_FOR_LEGAL = 3

_ARTICLE_FR = re.compile(
    r"^(?:Article|ARTICLE|Art\.)\s+"
    r"(premier|1er|unique|\d+(?:\s*(?:bis|ter|quater|quinquies|sexies|nouveau))?)"
    r"\s*(?:[-–.:]|$)",
    re.MULTILINE,
)
_ARTICLE_AR = re.compile(r"^\s*(?:الفصل|فصل)\s*(الأول|الوحيد|\d+)", re.MULTILINE)
_ARTICLE_NUMBERED = re.compile(r"^[ \t]*(1er|\d{1,3})\.[ \t]+", re.MULTILINE)
# A heading, not a reference: capitalised, numbered, and followed by its date.
# "Vu le décret n° 2008-733 du ..." wraps onto lines that start lowercase.
# Ministerial orders carry no number: "Arrêté du ministre des finances du 21 mai 2018".
_ACT = re.compile(
    r"^((?:Loi(?: organique)?|Décret(?:-loi| gouvernemental| présidentiel)?|Arrêté|Circulaire)"
    r"\s+n°\s*\d{2,4}\s*-\s*\d+)\s+du\s"
    r"|^(Arrêté (?:du|des|conjoint)[^\n]{3,90}? du \d{1,2}(?:er)? \w+ \d{4})",
    re.MULTILINE,
)


@dataclass
class Chunk:
    chunk_id: str
    point_id: str
    strategy: str
    doc_id: str
    title: str
    corpora: list[str]
    domain: str
    language: str
    path: str
    sha256: str
    publisher_url: str | None
    publication_date: str | None
    page_start: int
    page_end: int
    act: str | None
    article: str | None
    part: int
    parts: int
    text: str
    embed_text: str
    source_kind: str = "unknown"
    current_version_verified: bool = False
    extraction_method: str = "unknown"

    def payload(self) -> dict:
        data = asdict(self)
        data.pop("point_id")
        data.pop("embed_text")
        return data


@dataclass
class _Span:
    start: int
    end: int
    article: str | None = None
    act: str | None = None


class _Joined:
    """Pages joined into one string, with offsets mapped back to page numbers."""

    def __init__(self, pages: list[PageText]) -> None:
        self.page_sources = {p.page: p.source for p in pages}
        parts, self.starts, self.numbers = [], [], []
        offset = 0
        for page in pages:
            if not page.text:
                continue
            self.starts.append(offset)
            self.numbers.append(page.page)
            parts.append(page.text)
            offset += len(page.text) + 2
        self.text = "\n\n".join(parts)

    def page_at(self, offset: int) -> int:
        if not self.starts:
            return 1
        return self.numbers[max(0, bisect.bisect_right(self.starts, offset) - 1)]


def _snap(text: str, pos: int, window: int = 80) -> int:
    """Move a cut to the nearest whitespace before `pos`."""
    if pos >= len(text):
        return len(text)
    cut = text.rfind(" ", max(0, pos - window), pos)
    newline = text.rfind("\n", max(0, pos - window), pos)
    best = max(cut, newline)
    return best + 1 if best > 0 else pos


def _windows(text: str, start: int, end: int, size: int, overlap: int) -> list[tuple[int, int]]:
    spans, pos = [], start
    while pos < end:
        stop = min(end, _snap(text, pos + size)) if pos + size < end else end
        if stop <= pos:
            stop = min(end, pos + size)
        spans.append((pos, stop))
        if stop >= end:
            break
        pos = max(stop - overlap, pos + 1)
        pos = _snap(text, pos, window=40) if pos > start else pos
    return spans


_SEPARATORS = ("\n\n", "\n", ". ", "؛ ", "، ", " ")


def _recursive(text: str, start: int, end: int, budget: int, level: int = 0) -> list[tuple[int, int]]:
    """Split [start, end) on the coarsest separator that keeps pieces under budget."""
    if end - start <= budget or level >= len(_SEPARATORS):
        return [(start, end)] if text[start:end].strip() else []
    sep = _SEPARATORS[level]
    pieces, pos = [], start
    while pos < end:
        found = text.find(sep, pos, end)
        stop = end if found == -1 else found + len(sep)
        pieces.append((pos, stop))
        pos = stop
    out: list[tuple[int, int]] = []
    current: tuple[int, int] | None = None
    for piece in pieces:
        if piece[1] - piece[0] > budget:
            if current:
                out.append(current)
                current = None
            out.extend(_recursive(text, piece[0], piece[1], budget, level + 1))
        elif current and piece[1] - current[0] <= budget:
            current = (current[0], piece[1])
        else:
            if current:
                out.append(current)
            current = piece
    if current:
        out.append(current)
    return out


def _with_overlap(spans: list[tuple[int, int]], text: str, overlap: int) -> list[tuple[int, int]]:
    """Start each piece a little before the previous one ended."""
    out = []
    for index, (start, end) in enumerate(spans):
        if index and overlap:
            start = _snap(text, max(spans[index - 1][0], start - overlap), window=40)
        out.append((start, end))
    return out


def _article_spans(text: str, numbered: bool = False) -> list[_Span]:
    heads = [(m.start(), m.group(1)) for m in _ARTICLE_FR.finditer(text)]
    heads += [(m.start(), m.group(1)) for m in _ARTICLE_AR.finditer(text)]
    if not heads and numbered:
        heads = [(m.start(),m.group(1)) for m in _ARTICLE_NUMBERED.finditer(text)]
    heads.sort()
    if len(heads) < MIN_ARTICLES_FOR_LEGAL:
        return []
    acts = [(m.start(), re.sub(r"\s+", " ", m.group(1) or m.group(2))) for m in _ACT.finditer(text)]
    act_starts = [pos for pos, _ in acts]

    def act_at(pos: int) -> str | None:
        index = bisect.bisect_right(act_starts, pos) - 1
        return acts[index][1] if index >= 0 else None

    spans = []
    if heads[0][0] > 0:
        spans.append(_Span(0, heads[0][0], None, act_at(0)))
    for index, (pos, label) in enumerate(heads):
        end = heads[index + 1][0] if index + 1 < len(heads) else len(text)
        label = "1" if label in {"premier", "1er", "الأول"} else label.replace(" ", "")
        spans.append(_Span(pos, end, label, act_at(pos)))
    return spans


def _header(doc: SourceDocument, act: str | None, article: str | None, part: int, parts: int) -> str:
    bits = [doc.title]
    if act:
        bits.append(act)
    if article:
        bits.append(f"Article {article}" + (f" (part {part}/{parts})" if parts > 1 else ""))
    return " — ".join(bits)


def _make(doc, joined, strategy, n, start, end, act=None, article=None, part=1, parts=1) -> Chunk | None:
    while start < end and joined.text[start].isspace():
        start += 1
    while end > start and joined.text[end-1].isspace():
        end -= 1
    act = act or doc.extra.get("act")
    body = joined.text[start:end].strip()
    if len(body) < 40:
        return None
    chunk_id = f"{doc.doc_id}#{strategy}-{n:05d}"
    header = _header(doc, act, article, part, parts)
    language = detect_language(body) if doc.language is None else doc.language
    if any("؀" <= c <= "ۿ" for c in body[:200]):
        language = "ar"
    return Chunk(
        chunk_id=chunk_id,
        point_id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)),
        strategy=strategy,
        doc_id=doc.doc_id,
        title=doc.title,
        corpora=list(doc.corpora),
        domain=doc.domain,
        language=language,
        path=doc.rel_path,
        sha256=doc.sha256,
        publisher_url=doc.publisher_url,
        publication_date=doc.publication_date,
        page_start=joined.page_at(start),
        page_end=joined.page_at(max(start, end - 1)),
        act=act,
        article=article,
        part=part,
        parts=parts,
        text=body,
        embed_text=f"{header}\n{body}" if strategy == "structural" else body,
        source_kind=doc.extra.get("source_kind", "unknown"),
        current_version_verified=bool(doc.extra.get("current_version_verified", False)),
        extraction_method="ocr" if any(joined.page_sources.get(page) == "ocr" for page in range(joined.page_at(start), joined.page_at(max(start, end - 1)) + 1)) else "text",
    )


def chunk_fixed(doc: SourceDocument, pages: list[PageText]) -> list[Chunk]:
    joined = _Joined(pages)
    spans = _windows(joined.text, 0, len(joined.text), FIXED_SIZE, FIXED_OVERLAP)
    chunks = [_make(doc, joined, "fixed", n, s, e) for n, (s, e) in enumerate(spans)]
    return [c for c in chunks if c]


def chunk_structural(doc: SourceDocument, pages: list[PageText]) -> list[Chunk]:
    joined = _Joined(pages)
    text = joined.text
    articles = _article_spans(text,numbered=doc.extra.get("article_numbering") in {"bare_en","bare"})
    chunks: list[Chunk] = []
    if not articles:
        spans = _with_overlap(_recursive(text, 0, len(text), TARGET_CHARS), text, OVERLAP_CHARS)
        for start, end in spans:
            chunk = _make(doc, joined, "structural", len(chunks), start, end)
            if chunk:
                chunks.append(chunk)
        return chunks

    for span in articles:
        if span.end - span.start <= MAX_CHARS:
            pieces = [(span.start, span.end)]
        else:
            pieces = _with_overlap(
                _recursive(text, span.start, span.end, TARGET_CHARS), text, OVERLAP_CHARS
            )
        for part, (start, end) in enumerate(pieces, start=1):
            chunk = _make(
                doc, joined, "structural", len(chunks), start, end,
                act=span.act, article=span.article, part=part, parts=len(pieces),
            )
            if chunk:
                chunks.append(chunk)
    return chunks


STRATEGIES = {"fixed": chunk_fixed, "structural": chunk_structural}
