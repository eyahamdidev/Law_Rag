"""Resolve a catalogue source (file, page) to the indexed passage on that page.

Citations then carry the index's doc_id and the page's own text, so the
verifier checks them like any retrieved passage and no quote is written from
the catalogue. Without a built index (tests, fresh clone) a citation keeps
the file and page and has no quote.
"""

from functools import lru_cache

from app.config import settings
from app.modules.rag.ingestion.pipeline import load_chunks


def _key(path: str) -> str:
    return path.replace("\\", "/").lower()


@lru_cache(maxsize=1)
def _by_file() -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for row in load_chunks(settings.chunk_strategy):
        rows.setdefault(_key(row.get("path", "")), []).append(row)
    return rows


def source_chunk(source_file: str, page: int | None) -> dict | None:
    """The first indexed chunk of source_file that covers page, or None."""
    if not source_file or page is None:
        return None
    wanted = _key(source_file)
    for path, rows in _by_file().items():
        if path.endswith(wanted):
            for row in rows:
                if row["page_start"] <= page <= row["page_end"]:
                    return row
    return None
