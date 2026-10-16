"""HTTP client for the bp service. The gateway never imports bp code (rule: modules talk over HTTP + JSON)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

import httpx

from app.config import settings

_REF = re.compile(r"^[0-9a-f]{64}$")
_CT = {"png": "image/png", "json": "application/json",
       "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
       "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


class BpUnavailable(RuntimeError):
    pass


def store_upload(data: bytes) -> str:
    """Files travel by reference: /data/uploads/<sha256>. The request to bp carries the reference only."""
    digest = hashlib.sha256(data).hexdigest()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    target = settings.uploads_dir / digest
    if not target.exists():
        target.write_bytes(data)
    return digest


def read_artifact_json(ref: str) -> dict | None:
    if not _REF.fullmatch(ref):
        return None
    path = settings.uploads_dir / ref
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def artifact_path(ref: str) -> Path | None:
    if not _REF.fullmatch(ref):
        return None
    path = settings.uploads_dir / ref
    return path if path.is_file() else None


def content_type(kind: str) -> str:
    return _CT.get(kind, "application/octet-stream")


def _post(path: str, payload: dict, timeout: float | None = None, transport: httpx.BaseTransport | None = None):
    try:
        with httpx.Client(transport=transport, timeout=timeout or settings.bp_timeout_s) as c:
            return c.post(f"{settings.bp_service_url.rstrip('/')}{path}", json=payload)
    except httpx.HTTPError as exc:
        raise BpUnavailable(f"The business-plan service is not reachable at {settings.bp_service_url} ({exc.__class__.__name__}).") from exc


def run(*, lang: str, file_ref: str | None, profile: dict, options: dict, question: str | None = None, transport=None) -> tuple[int, dict]:
    payload = {"request_id": uuid.uuid4().hex, "workspace": "bp", "lang": lang, "file_ref": file_ref,
               "profile": profile or None, "options": options or None, "question": question}
    r = _post("/v1/run", payload, transport=transport)
    return r.status_code, r.json()


def questionnaire(*, lang: str, profile: dict, answers: dict, template: str | None, transport=None) -> tuple[int, dict]:
    r = _post("/v1/questionnaire", {"lang": lang, "profile": profile or None, "answers": answers or None, "template": template},
              timeout=15.0, transport=transport)
    return r.status_code, r.json()


def chat(*, lang: str, profile: dict, state: dict | None, message: str | None, action: str | None, transport=None) -> tuple[int, dict]:
    r = _post("/v1/chat", {"lang": lang, "profile": profile or None, "state": state, "message": message, "action": action},
              timeout=15.0, transport=transport)
    return r.status_code, r.json()
