"""Structured funding and aid catalog loader with provenance tracking.

Every condition is grounded in a source document and page number.
"""

from pathlib import Path
import yaml

from app.schemas.aid import AidProgram

CATALOG_YAML_PATH = Path(__file__).with_name("catalog.yaml")


def load_catalog(path: Path = CATALOG_YAML_PATH) -> list[AidProgram]:
    """Load and validate the aid catalog from YAML."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    raw_programs = data.get("programs", [])
    return [AidProgram.model_validate(item) for item in raw_programs]


CATALOG: list[AidProgram] = load_catalog()


def get_program(program_id: str) -> AidProgram | None:
    """Retrieve a program by id."""
    for prog in CATALOG:
        if prog.id == program_id:
            return prog
    return None


def all_programs() -> list[AidProgram]:
    """Return all catalog programs."""
    return list(CATALOG)
