"""Files travel by reference (rule 7): /data/uploads/<sha256>. Requests carry file_ref, never bytes."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.config import settings
from app.contract import ModuleError

_REF = re.compile(r"^[0-9a-f]{64}$")
MAX_BYTES = 25 * 1024 * 1024


def resolve(file_ref: str) -> Path:
    if not _REF.fullmatch(file_ref or ""):
        raise ModuleError("BAD_INPUT", "file_ref must be a 64-character lowercase sha256.")
    path = settings.uploads_dir / file_ref
    if not path.is_file():
        raise ModuleError("BAD_INPUT", f"No upload found for file_ref {file_ref[:12]}…")
    if path.stat().st_size > MAX_BYTES:
        raise ModuleError("UNSUPPORTED_FILE", "File is larger than 25 MB.")
    return path


def read(file_ref: str) -> bytes:
    return resolve(file_ref).read_bytes()


def put(data: bytes) -> str:
    """Store bytes under their sha256 and return the reference."""
    digest = hashlib.sha256(data).hexdigest()
    directory = settings.uploads_dir
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / digest
    if not target.exists():
        tmp = directory / f".{digest}.tmp"
        tmp.write_bytes(data)
        tmp.replace(target)
    return digest
