"""Shared status and trace types."""

from enum import Enum

from pydantic import BaseModel, Field


class ModuleStatus(str, Enum):
    ok = "ok"
    placeholder = "placeholder"
    skipped = "skipped"


class TraceStep(BaseModel):
    module: str
    status: ModuleStatus
    detail: str = ""


class ModuleInfo(BaseModel):
    id: str
    pillar: str
    role: str
    status: ModuleStatus = ModuleStatus.placeholder


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


class CorpusFolder(BaseModel):
    path: str
    exists: bool
    file_count: int
    pdf_count: int


class CorpusInventory(BaseModel):
    law: CorpusFolder
    aid: CorpusFolder
    fraud: CorpusFolder
    note: str = Field(
        default=(
            "Counts are files on disk. They are not a legal-currency audit "
            "and they are not an eligibility ruling."
        )
    )
