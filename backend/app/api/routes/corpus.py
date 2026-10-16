"""On-disk corpus counts for the three data folders."""

from fastapi import APIRouter

from app.modules.rag.ingestion.inventory import inventory
from app.schemas.common import CorpusInventory

router = APIRouter()


@router.get("/corpus", response_model=CorpusInventory)
def corpus() -> CorpusInventory:
    return inventory()