"""Read an uploaded business plan (pdf, docx, xlsx, txt) into blocks and tables.

This module does not run OCR. A PDF page with no text layer is flagged, and the
caller may send its image to the vision model (see ``page_images``). Legacy
``.doc`` and ``.xls`` files are refused with a clear message: save them as
``.docx`` / ``.xlsx`` first.
"""

from __future__ import annotations

import base64
import io
import re
import statistics
import zipfile
from dataclasses import dataclass, field

from app.contract import ModuleError

HEADING_NUM = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]|[IVX]+[.)]|[A-Z][.)]|chapitre\s+\d+|partie\s+\d+)\s+\S", re.I)


@dataclass
class Block:
    text: str
    kind: str = "para"  # heading | para
    page: int | None = None
    bbox: list[float] | None = None
    level: int = 1


@dataclass
class Table:
    rows: list[list[str]]
    page: int | None = None
    name: str = ""
    bbox: list[float] | None = None


@dataclass
class Document:
    kind: str
    blocks: list[Block] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    page_count: int | None = None
    scanned_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: bytes = b""

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


def detect_kind(data: bytes) -> str:
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:2] == b"PK":
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile as exc:
            raise ModuleError("UNSUPPORTED_FILE", "The file looks like a zip archive but is damaged.") from exc
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        raise ModuleError("UNSUPPORTED_FILE", "Zip archive that is not a Word or Excel file.")
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ModuleError("UNSUPPORTED_FILE", "Legacy .doc/.xls files are not read. Save the file as .docx or .xlsx and upload it again.")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ModuleError("UNSUPPORTED_FILE", "Unrecognised file type. Use pdf, docx, xlsx or plain text.") from exc
    return "txt"


def looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90 or s.endswith((".", ";", ",")):
        return False
    if HEADING_NUM.match(s):
        return True
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and s.upper() == s and len(letters) >= 4


def read_document(data: bytes) -> Document:
    kind = detect_kind(data)
    doc = {"pdf": _pdf, "docx": _docx, "xlsx": _xlsx, "txt": _txt}[kind](data)
    doc.raw = data
    if not doc.text.strip() and not doc.tables:
        doc.warnings.append("No readable text was found in the file.")
    return doc


# ---------------------------------------------------------------------------- txt
def _txt(data: bytes) -> Document:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    doc = Document(kind="txt")
    rows: list[list[str]] = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for k, line in enumerate(lines):
        if "\t" in line or line.count("|") >= 2 or re.search(r"\S\s{3,}\S", line):
            cells = [c.strip() for c in re.split(r"\t|\||\s{3,}", line) if c.strip()]
            if len(cells) >= 2:
                rows.append(cells)
                continue
        if rows:
            doc.tables.append(Table(rows=rows, name=doc.blocks[-1].text if doc.blocks else ""))
            rows = []
        s = line.strip()
        short_title = (len(s.split()) <= 6 and len(s) <= 60 and not re.search(r"[.:;,\d]$|\d", s)
                       and k + 1 < len(lines))
        doc.blocks.append(Block(s, "heading" if (looks_like_heading(s) or short_title) else "para"))
    if rows:
        doc.tables.append(Table(rows=rows, name=doc.blocks[-1].text if doc.blocks else ""))
    return doc


# ---------------------------------------------------------------------------- docx
def _docx(data: bytes) -> Document:
    import docx  # python-docx
    from docx.table import Table as DTable
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    doc = Document(kind="docx")
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            txt = p.text.strip()
            if not txt:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            is_head = bool(re.match(r"(heading|titre|title)", style, re.I)) or looks_like_heading(txt)
            level = 1
            m = re.search(r"(\d)", style)
            if m:
                level = int(m.group(1))
            doc.blocks.append(Block(txt, "heading" if is_head else "para", level=level))
        elif tag == "tbl":
            t = DTable(child, d)
            rows = [[c.text.strip() for c in r.cells] for r in t.rows]
            rows = [r for r in rows if any(r)]
            if rows:
                doc.tables.append(Table(rows=rows, name=doc.blocks[-1].text if doc.blocks else ""))
    return doc


# ---------------------------------------------------------------------------- xlsx
def _xlsx(data: bytes) -> Document:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    doc = Document(kind="xlsx")
    formulas_without_cache = False
    for ws in wb.worksheets:
        rows: list[list[str]] = []
        for r in ws.iter_rows(values_only=True):
            cells = ["" if v is None else (f"{v:g}" if isinstance(v, float) else str(v)) for v in r]
            if any(c.strip() for c in cells):
                rows.append([c.strip() for c in cells])
        if rows:
            doc.blocks.append(Block(ws.title, "heading", level=1))
            doc.tables.append(Table(rows=rows, name=ws.title))
            # plain text lines for single-cell rows (titles, notes)
            for r in rows:
                filled = [c for c in r if c]
                if len(filled) == 1 and len(filled[0]) > 3:
                    doc.blocks.append(Block(filled[0], "heading" if looks_like_heading(filled[0]) else "para"))
    if not doc.tables:
        formulas_without_cache = True
    if formulas_without_cache:
        doc.warnings.append("The workbook has no cached values. Open and save it in Excel so formulas keep their results.")
    return doc


# ---------------------------------------------------------------------------- pdf
def _pdf(data: bytes) -> Document:
    import pymupdf

    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ModuleError("UNSUPPORTED_FILE", "The PDF could not be opened.") from exc
    if pdf.needs_pass:
        raise ModuleError("UNSUPPORTED_FILE", "The PDF is password protected.")
    doc = Document(kind="pdf", page_count=pdf.page_count)
    sizes: list[float] = []
    pages = []
    for i, page in enumerate(pdf, start=1):
        info = page.get_text("dict")
        pages.append((i, info))
        for b in info["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    if sp["text"].strip():
                        sizes.append(sp["size"])
    body = statistics.median(sizes) if sizes else 11.0
    for i, info in pages:
        text_chars = 0
        for b in info["blocks"]:
            if b.get("type") != 0:
                continue
            bbox = [round(x, 1) for x in b["bbox"]]
            para: list[str] = []

            def flush() -> None:
                if para:
                    doc.blocks.append(Block(" ".join(para).strip(), "para", page=i, bbox=bbox))
                    para.clear()

            for ln in b["lines"]:
                spans = [sp for sp in ln["spans"] if sp["text"].strip()]
                t = "".join(sp["text"] for sp in ln["spans"]).strip()
                if not t:
                    continue
                text_chars += len(t)
                big = any(sp["size"] >= body * 1.15 for sp in spans)
                bold = bool(spans) and all(sp["flags"] & 16 or "bold" in sp.get("font", "").lower() for sp in spans)
                is_head = len(t) < 100 and (big or looks_like_heading(t) or (bold and len(t) < 70 and not t.endswith((".", ","))))
                if is_head:
                    flush()
                    doc.blocks.append(Block(t, "heading", page=i, bbox=bbox))
                else:
                    para.append(t)
            flush()
        if text_chars < 20:
            doc.scanned_pages.append(i)
    if doc.scanned_pages:
        doc.warnings.append(
            f"Pages {', '.join(map(str, doc.scanned_pages[:10]))} have no text layer (scan). "
            "This module does not run OCR; a vision model may read them if configured."
        )
    for i, page in enumerate(pdf, start=1):
        try:
            for t in page.find_tables().tables:
                rows = [[(c or "").strip() for c in r] for r in t.extract()]
                rows = [r for r in rows if any(r)]
                if rows:
                    doc.tables.append(Table(rows=rows, page=i, bbox=[round(x, 1) for x in t.bbox]))
        except Exception:  # noqa: BLE001  table finding is best effort
            continue
    return doc


def page_images(doc: Document, pages: list[int] | None = None, max_pages: int = 3, dpi: int = 110) -> list[str]:
    """Render PDF pages to base64 PNG for the vision model."""
    if doc.kind != "pdf":
        return []
    import pymupdf

    pdf = pymupdf.open(stream=doc.raw, filetype="pdf")
    want = (pages or doc.scanned_pages or [])[:max_pages]
    out = []
    for n in want:
        pix = pdf[n - 1].get_pixmap(dpi=dpi)
        out.append(base64.b64encode(pix.tobytes("png")).decode())
    return out
