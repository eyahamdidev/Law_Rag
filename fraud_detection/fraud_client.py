"""HTTP client for the fraud scoring service.

The orchestration agent should call ``score_transaction``. This module does not
import models, feature code, the graph, or the sanctions index.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx


def health(base_url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=timeout)
    response.raise_for_status()
    return response.json()


def _post(base_url: str, path: str, payload: dict[str, Any], timeout: float, client: httpx.Client | None) -> dict[str, Any]:
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        response = client.post(f"{base_url.rstrip('/')}{path}", json=payload)
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            client.close()


def enroll_mark(
    base_url: str,
    entity_id: str,
    kind: str,
    image_bytes: bytes,
    *,
    comment: str | None = None,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Crop and save a genuine stamp or signature. The store starts empty."""
    return _post(
        base_url,
        "/v1/documents/enroll",
        {
            "entity_id": entity_id,
            "kind": kind,
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "comment": comment,
        },
        timeout,
        client,
    )


def check_document(
    base_url: str,
    entity_id: str,
    image_bytes: bytes,
    *,
    expect_stamp: bool = True,
    expect_signature: bool = True,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Warn when an expected mark is missing or does not match the enrolled specimen."""
    return _post(
        base_url,
        "/v1/documents/check",
        {
            "entity_id": entity_id,
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "expect_stamp": expect_stamp,
            "expect_signature": expect_signature,
        },
        timeout,
        client,
    )


def decide_document_mark(
    base_url: str,
    proposal_id: str,
    approve: bool,
    *,
    comment: str | None = None,
    tenant_secret: str | None = None,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Save or discard a stamp or signature that scoring already cropped."""
    return _post(
        base_url,
        "/v1/documents/decide",
        {
            "proposal_id": proposal_id,
            "approve": approve,
            "comment": comment,
            "tenant_secret": tenant_secret,
        },
        timeout,
        client,
    )


def score_transaction(
    base_url: str,
    transaction: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    entities: list[dict[str, Any]] | None = None,
    *,
    document: bytes | None = None,
    document_filename: str | None = None,
    document_entity_id: str | None = None,
    expect_stamp: bool = True,
    expect_signature: bool = True,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Score one payment. A PDF or image is cropped and reviewed inside the same call."""
    payload: dict[str, Any] = {"transaction": transaction}
    if history:
        payload["history"] = history
    if entities:
        payload["entities"] = entities
    if document is not None:
        encoded = base64.b64encode(document).decode("ascii")
        name = (document_filename or "").lower()
        field = "pdf_base64" if name.endswith(".pdf") or document.startswith(b"%PDF-") else "image_base64"
        payload["document"] = {
            field: encoded,
            "filename": document_filename,
            "entity_id": document_entity_id,
            "expect_stamp": expect_stamp,
            "expect_signature": expect_signature,
        }
    return _post(base_url, "/v1/score", payload, timeout, client)
