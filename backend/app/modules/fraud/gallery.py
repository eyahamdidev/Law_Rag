"""Read enrolled stamp specimens for the fraud tab gallery (local specimen store)."""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

from app.config import settings


def _specimen_root() -> Path:
    return settings.fraud_data_dir / "data" / "specimens"


def _tenant_secret(entity_id: str, root: Path) -> str | None:
    path = root / "tenants.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return (payload.get("secrets") or {}).get(entity_id)


def _tenant_locked(entity_id: str, rows: list[dict]) -> bool:
    return any(row.get("entity_id") == entity_id for row in rows)


def _authorized(entity_id: str, presented: str | None, root: Path, rows: list[dict]) -> bool:
    if not _tenant_locked(entity_id, rows):
        return True
    stored = _tenant_secret(entity_id, root)
    offered = " ".join((presented or "").split())
    if not stored or not offered:
        return False
    return secrets.compare_digest(stored, offered)


def list_saved_stamps(entity_id: str, tenant_secret: str | None) -> tuple[list[dict], str | None]:
    root = _specimen_root()
    index_path = root / "index.json"
    if not index_path.is_file():
        return [], None
    rows = list(json.loads(index_path.read_text(encoding="utf-8")).get("specimens") or [])
    if not _authorized(entity_id, tenant_secret, root, rows):
        return [], "locked"
    stamps: list[dict] = []
    for row in rows:
        if row.get("entity_id") != entity_id or row.get("kind") != "stamp":
            continue
        specimen_id = str(row.get("specimen_id") or "")
        preview: str | None = None
        png = root / f"{specimen_id}.png"
        if png.is_file():
            preview = base64.b64encode(png.read_bytes()).decode("ascii")
        stamps.append(
            {
                "specimen_id": specimen_id,
                "comment": str(row.get("comment") or ""),
                "read_text": str(row.get("read_text") or ""),
                "created_at": str(row.get("created_at") or ""),
                "preview_base64": preview,
            }
        )
    stamps.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return stamps, None
