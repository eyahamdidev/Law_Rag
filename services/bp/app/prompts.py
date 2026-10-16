"""Prompt library loader: prompts/bp/<prompt_id>/v<N>.yaml (spec 2.6)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import SERVICE_ROOT

PROMPT_DIR = SERVICE_ROOT / "prompts" / "bp"


@lru_cache(maxsize=64)
def load(prompt_id: str, version: int | None = None) -> dict:
    folder = PROMPT_DIR / prompt_id
    if version is None:
        versions = sorted(int(re.search(r"v(\d+)", p.stem).group(1)) for p in folder.glob("v*.yaml"))
        if not versions:
            raise FileNotFoundError(f"No prompt versions for {prompt_id}")
        version = versions[-1]
    data = yaml.safe_load((folder / f"v{version}.yaml").read_text(encoding="utf-8"))
    return data


def ref(p: dict) -> str:
    return f"{p['id']}@v{p['version']}"


def render(text: str, **values: str) -> str:
    out = text
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out
