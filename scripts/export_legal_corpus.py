"""Export legal sources and passages to UTF-8 CSV without exporting personal contracts."""
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

if __name__ == "__main__":
    from app.config import settings
    from app.modules.rag.ingestion.pipeline import load_chunks
    rows = [r for r in load_chunks(settings.chunk_strategy) if "law" in r["corpora"]]
    folder = settings.data_dir / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    fields = ["chunk_id","doc_id","title","domain","language","act","article","page_start","page_end","publication_date","publisher_url","path","sha256","source_kind","current_version_verified","extraction_method","text"]
    with (folder / "legal_passages.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    unique = {r["doc_id"]: r for r in rows}
    source_fields = [f for f in fields if f not in {"chunk_id","act","article","page_start","page_end","text"}]
    with (folder / "legal_sources.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=source_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unique.values())
    print(f"Exported {len(unique)} sources and {len(rows)} legal passages to {folder}")
