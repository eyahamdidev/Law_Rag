"""Count files already stored for each pillar."""

from pathlib import Path

from app.config import settings
from app.schemas.common import CorpusFolder, CorpusInventory


def _folder(path: Path) -> CorpusFolder:
    if not path.exists():
        return CorpusFolder(path=str(path), exists=False, file_count=0, pdf_count=0)
    files = [item for item in path.rglob("*") if item.is_file() and item.name != ".gitkeep"]
    pdfs = [item for item in files if item.suffix.lower() == ".pdf"]
    return CorpusFolder(
        path=str(path),
        exists=True,
        file_count=len(files),
        pdf_count=len(pdfs),
    )


def inventory() -> CorpusInventory:
    return CorpusInventory(
        law=_folder(settings.law_corpus_dir),
        aid=_folder(settings.aid_corpus_dir),
        fraud=_folder(settings.fraud_data_dir),
    )
