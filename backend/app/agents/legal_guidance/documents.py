"""Bounded in-memory document intake; local OCR by default, no persistent uploads."""
from io import BytesIO
from pathlib import Path
import zipfile

import pymupdf

from app.config import settings
from app.modules.rag.ingestion.extract import normalize
from app.schemas.agents import Attachment
from app.schemas.legal import ExtractedDocument

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 40
MAX_TEXT = 12000

def _local_ocr(image: bytes):
    import tesserocr
    from PIL import Image
    with tesserocr.PyTessBaseAPI(path=str(settings.data_dir / "tessdata"), lang="ara+fra+eng") as api:
        api.SetImage(Image.open(BytesIO(image)))
        return normalize(api.GetUTF8Text()), api.MeanTextConf()

def extract_document(filename: str, content: bytes, use_ocr: bool = False, page_start: int = 1, page_end: int | None = None) -> ExtractedDocument:
    filename = Path(filename.replace("\\", "/")).name[:200]
    suffix = Path(filename).suffix.lower()
    warnings, gaps, texts = [], [], []
    extraction = "text"
    pages = None
    if suffix == ".pdf":
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise ValueError("Encrypted PDF: provide an unlocked copy")
            if len(pdf) > 600:
                raise ValueError("PDF is limited to 600 pages; provide a relevant extract")
            pages = len(pdf)
            stop = page_end if page_end is not None else min(pages,page_start+MAX_PAGES-1)
            if not 1 <= page_start <= stop <= pages or stop-page_start+1 > MAX_PAGES:
                raise ValueError(f"Choose a valid PDF range of at most {MAX_PAGES} pages")
            if page_start != 1 or stop != pages:
                warnings.append(f"Only PDF pages {page_start}–{stop} of {pages} were read for this request")
            ocr_used = 0
            for number in range(page_start,stop+1):
                page=pdf[number-1]
                text = normalize(page.get_text())
                corrupt = sum(ord(c) < 32 and c not in "\n\r\t" for c in text) / max(len(text), 1) > .01
                if len(text) < 60 or corrupt:
                    text = ""
                    gaps.append(number)
                    if use_ocr and ocr_used < 4:
                        if page.rect.width * page.rect.height * (180 / 72) ** 2 > 16000000:
                            warnings.append("A page exceeds the local OCR pixel limit; it was not rasterized")
                            continue
                        try:
                            text, confidence = _local_ocr(page.get_pixmap(dpi=180).tobytes("png"))
                            if confidence < 25:
                                text = ""
                            else:
                                gaps.remove(number)
                            ocr_used += 1
                            extraction = "local_ocr"
                        except (ImportError, RuntimeError):
                            warnings.append("Local OCR is unavailable for this page")
                if text:
                    texts.append(f"[page {number}]\n{text}")
    elif suffix == ".txt":
        if page_start != 1 or page_end is not None:
            raise ValueError("Page ranges apply only to PDF files")
        texts = [content.decode("utf-8-sig", errors="strict")]
    elif suffix == ".docx":
        if page_start != 1 or page_end is not None:
            raise ValueError("Page ranges apply only to PDF files")
        from docx import Document
        from docx.opc.exceptions import OpcError
        with zipfile.ZipFile(BytesIO(content)) as package:
            if sum(i.file_size for i in package.infolist()) > 30 * 1024 * 1024:
                raise ValueError("Expanded DOCX exceeds the size limit")
        try:
            doc = Document(BytesIO(content))
        except (OpcError, KeyError) as error:
            raise ValueError("Invalid Word document package") from error
        texts = [p.text for p in doc.paragraphs] + [" | ".join(c.text for c in row.cells) for table in doc.tables for row in table.rows]
    else:
        raise ValueError("Supported document formats: PDF, DOCX, UTF-8 TXT")
    text = "\n\n".join(texts)
    if len(text) > MAX_TEXT:
        warnings.append(f"Extracted text was limited to {MAX_TEXT} characters")
    if gaps:
        warnings.append("Some pages remain unreadable; do not infer facts from those pages")
    return ExtractedDocument(attachment=Attachment(filename=filename, mime={".pdf":"application/pdf", ".docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".txt":"text/plain"}[suffix],
                                                  text=text[:MAX_TEXT], pages=pages, extraction=extraction), needs_ocr_pages=gaps, warnings=list(dict.fromkeys(warnings)))
