"""Turn an upload (PDF, scan, photo, text) into text the agents can read.

- Digital PDF: PyMuPDF text, with the same font repair and normalisation as
  the corpus (rag/ingestion/extract.py).
- Scanned PDF pages and images: rendered to PNG and transcribed by the vision
  model (prompt intake.ocr_page). Capped per upload to stay inside free quotas.
- Plain text: decoded.

The same `ocr_pdf_pages` function fills data/ocr/ for the scanned corpus PDFs:

    python -m app.modules.intake.extractor --corpus-ocr --max-pages 40
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import pymupdf

from app.modules.rag.ingestion.extract import extract_pages, normalize, ocr_cache_path
from app.prompts.library import get_prompt
from app.schemas.agents import Attachment
from app.schemas.common import ModuleStatus, TraceStep
from app.services.llm import LLMUnavailable, get_llm

MAX_UPLOAD_OCR_PAGES = 4
MAX_ATTACHMENT_CHARS = 12000
IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def _vision_text(image: bytes, mime: str = "image/png") -> str:
    prompt = get_prompt("intake.ocr_page")
    return get_llm().vision(image, prompt.messages()[-1]["content"], mime=mime).text


def ocr_pdf_pages(path: Path, sha256: str, pages: list[int], dpi: int = 150, pause_s: float = 4.0) -> int:
    """OCR the given 1-based pages into the cache. Returns pages written."""
    written = 0
    with pymupdf.open(path) as doc:
        for number in pages:
            target = ocr_cache_path(sha256, number)
            if target.exists():
                continue
            image = doc[number - 1].get_pixmap(dpi=dpi).tobytes("png")
            text = _vision_text(image)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            written += 1
            time.sleep(pause_s)  # free-tier requests per minute
    return written


def inspect_document(filename: str, content: bytes, mime: str) -> tuple[Attachment, TraceStep]:
    mime = (mime or "").lower()
    name = filename.lower()
    try:
        if mime == "application/pdf" or name.endswith(".pdf"):
            return _from_pdf(filename, content)
        if mime in IMAGE_TYPES or name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            text = normalize(_vision_text(content, mime if mime in IMAGE_TYPES else "image/png"))
            attachment = Attachment(filename=filename, mime=mime or "image", text=text[:MAX_ATTACHMENT_CHARS], extraction="vision")
            return attachment, TraceStep(module="intake.vision", status=ModuleStatus.ok, detail=f"{filename}: {len(text)} chars read from the image.")
        text = content.decode("utf-8", errors="replace")
        attachment = Attachment(filename=filename, mime=mime or "text/plain", text=text[:MAX_ATTACHMENT_CHARS])
        return attachment, TraceStep(module="intake.text", status=ModuleStatus.ok, detail=f"{filename}: {len(text)} chars.")
    except LLMUnavailable as error:
        attachment = Attachment(filename=filename, mime=mime, extraction="none")
        return attachment, TraceStep(module="intake", status=ModuleStatus.skipped, detail=f"{filename}: vision unavailable ({str(error)[:120]}).")


def _from_pdf(filename: str, content: bytes) -> tuple[Attachment, TraceStep]:
    sha = hashlib.sha256(content).hexdigest()
    tmp = Path(ocr_cache_path(sha, 0)).parent / "upload.pdf"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(content)
    pages = extract_pages(tmp, sha)
    sparse = [p.page for p in pages if p.needs_ocr][:MAX_UPLOAD_OCR_PAGES]
    extraction = "text"
    if sparse:
        try:
            ocr_pdf_pages(tmp, sha, sparse, pause_s=0)
            pages = extract_pages(tmp, sha)
            extraction = "ocr"
        except LLMUnavailable:
            extraction = "text (scanned pages not read: no vision model)"
    text = "\n\n".join(f"[page {p.page}]\n{p.text}" for p in pages if p.text)
    attachment = Attachment(filename=filename, mime="application/pdf", text=text[:MAX_ATTACHMENT_CHARS], pages=len(pages), extraction=extraction)
    detail = f"{filename}: {len(pages)} pages, {len(text)} chars, OCR on {len(sparse)} scanned pages." if sparse else f"{filename}: {len(pages)} pages, {len(text)} chars of digital text."
    return attachment, TraceStep(module="intake.pdf", status=ModuleStatus.ok, detail=detail)


def corpus_ocr(max_pages: int) -> None:
    from app.config import settings
    from app.modules.rag.ingestion.sources import discover

    report = json.loads((settings.data_dir / "index" / "report.json").read_text(encoding="utf-8"))
    gaps = {row["doc_id"]: row["needs_ocr_pages"] for row in report if row.get("needs_ocr_pages")}
    docs = {d.doc_id: d for d in discover(("law", "grants"))}
    budget = max_pages
    for doc_id, pages in sorted(gaps.items(), key=lambda kv: not kv[0].startswith("law:")):
        if budget <= 0:
            break
        doc = docs.get(doc_id)
        if not doc:
            continue
        todo = [p for p in pages if not ocr_cache_path(doc.sha256, p).exists()][:budget]
        if not todo:
            continue
        print(f"{doc_id}: OCR {len(todo)} pages", flush=True)
        budget -= ocr_pdf_pages(doc.path, doc.sha256, todo)
    print("Re-run the ingestion pipeline to index the OCR text.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-ocr", action="store_true")
    parser.add_argument("--max-pages", type=int, default=40)
    args = parser.parse_args()
    if args.corpus_ocr:
        corpus_ocr(args.max_pages)
