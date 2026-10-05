"""Ingestion pipeline placeholder.

Planned steps, matching the deck:
1. Extract digital text. OCR scanned pages and flag uncertain pages.
2. Store publisher, language, document hash, edition, article, page, highlight.
3. Keep article boundaries. Split long articles into linked passages.
4. Leave unknown publication or effective dates unknown.

Wire this to pypdf and the Qdrant writer in services/vectorstore.py.
"""

from app.schemas.common import ModuleStatus, TraceStep


def run_ingestion() -> TraceStep:
    return TraceStep(
        module="rag.ingestion",
        status=ModuleStatus.placeholder,
        detail="Ingestion is not connected. The corpus inventory only counts files on disk.",
    )
