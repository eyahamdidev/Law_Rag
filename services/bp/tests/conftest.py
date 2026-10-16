import os

import pytest

os.environ.setdefault("BP_LLM", "off")
os.environ["BP_VECTOR_STORE"] = "off"


@pytest.fixture(autouse=True)
def uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("BP_LLM", "off")
    monkeypatch.setenv("LLM_API_KEY", "")
    return tmp_path / "uploads"
