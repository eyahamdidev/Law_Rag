"""Aid and financing match contract."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ModuleStatus, TraceStep


class AidProfile(BaseModel):
    stage: Literal["creation", "extension", "growth", "unspecified"] = "unspecified"
    sector: str = ""
    need: Literal["financing", "grant", "tax_incentive", "guidance", "unspecified"] = (
        "unspecified"
    )


class AidProgram(BaseModel):
    id: str
    name: str
    provider: str
    summary: str
    stages: list[str]
    local_files: list[str] = Field(default_factory=list)


class AidMatchResponse(BaseModel):
    status: ModuleStatus
    programs: list[AidProgram]
    summary: str
    trace: list[TraceStep]
