"""Resume local Arabic/French/English OCR; no cloud calls or private document uploads."""
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

def process_document(job):
    path, digest, page_numbers, language, redo = job
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    import pymupdf
    import tesserocr
    from PIL import Image
    from app.modules.rag.ingestion.extract import normalize, ocr_cache_path
    records = []
    arabic = language == "ar"
    with pymupdf.open(path) as pdf, tesserocr.PyTessBaseAPI(path=str(ROOT / "data" / "tessdata"), lang="ara" if arabic else "ara+fra+eng") as api:
        for number in page_numbers:
            target = ocr_cache_path(digest, number)
            if target.exists() and not redo:
                continue
            image = Image.open(BytesIO(pdf[number - 1].get_pixmap(dpi=220 if arabic else 180, annots=False).tobytes("png")))
            if arabic:
                # Remove light grey watermarks from the OCR input only, preserving the original PDF.
                image = image.convert("L").point(lambda value: 0 if value < 110 else 255)
            api.SetImage(image)
            text = normalize(api.GetUTF8Text())
            confidence = api.MeanTextConf()
            if len(text.strip()) >= 40 and confidence >= 25:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            elif redo and target.exists():
                target.unlink()  # do not keep an older low-quality transcription as evidence
            records.append({"page": number, "confidence": confidence, "characters": len(text), "cached": target.exists()})
    return {"path": path, "pages": records, "review_required": True}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filename", help="Only process this document filename")
    parser.add_argument("--redo", action="store_true", help="Replace existing machine OCR for the selected document")
    args = parser.parse_args()
    from app.modules.rag.ingestion.sources import discover
    from app.modules.rag.ingestion.extract import extract_pages
    jobs = []
    for document in discover(("law",)):
        if args.filename and document.path.name != args.filename:
            continue
        needed = [p.page for p in extract_pages(document.path, document.sha256) if p.needs_ocr or args.redo]
        if needed:
            jobs.append((str(document.path), document.sha256, needed, document.language, args.redo))
    print(f"Local OCR: {sum(len(j[2]) for j in jobs)} pages in {len(jobs)} documents", flush=True)
    report_path = ROOT / "data" / "ocr-report.json"
    previous = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else []
    replacing = {job[0] for job in jobs}
    report = [record for record in previous if record.get("path") not in replacing]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(process_document, job): job[0] for job in jobs}
        for future in as_completed(futures):
            try:
                record = future.result()
                report.append(record)
                print(f"OCR complete: {Path(record['path']).name} ({len(record['pages'])} pages)", flush=True)
            except Exception as error:
                report.append({"path": futures[future], "error": str(error)})
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OCR complete; machine transcriptions still need accuracy review.", flush=True)

if __name__ == "__main__":
    main()
