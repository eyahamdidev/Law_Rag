"""Gateway side of the business-plan workspace.

The bp service has its own test suite. Here the real service is started as a
subprocess (same HTTP contract the gateway uses in production) and the gateway is
driven through its API: upload, questionnaire, shared profile, downloads.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.modules.orchestrator import profile as sp

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def bp_service(tmp_path_factory):
    uploads = tmp_path_factory.mktemp("uploads")
    port = _free_port()
    env = {**os.environ, "UPLOADS_DIR": str(uploads), "BP_LLM": "off", "BP_VECTOR_STORE": "off", "LLM_API_KEY": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--app-dir", str(ROOT / "services" / "bp")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(url + "/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("bp service did not start")
    old = (settings.bp_service_url, settings.uploads_dir)
    settings.bp_service_url, settings.uploads_dir = url, uploads
    yield url
    settings.bp_service_url, settings.uploads_dir = old
    proc.terminate()


def _client():
    return TestClient(create_app())


H = {"X-Session-Id": "test-session-1"}


def test_router_sends_business_plan_questions_to_bp():
    body = _client().post("/api/chat", json={"question": "Peux-tu relire mon business plan ?"}).json()
    assert body["intent"] == "bp"
    aid = _client().post("/api/chat", json={"question": "Quels documents BFPME pour une subvention ?"}).json()
    assert aid["intent"] == "aid"


def test_chat_and_aid_feed_the_session_profile():
    sp.clear("s-feed")
    c = _client()
    c.post("/api/chat", json={"question": "Je veux créer une SARL, j'ai besoin d'un financement de 80 000 DT pour 4 salariés"}, headers={"X-Session-Id": "s-feed"})
    got = c.get("/api/profile", headers={"X-Session-Id": "s-feed"}).json()["profile"]
    assert got["legal_form"] == "SARL" and got["stage"] == "creation" and got["funding_amount"] == 80000 and got["headcount"] == 4
    c.post("/api/aid/match", json={"stage": "extension", "sector": "textile", "need": "grant"}, headers={"X-Session-Id": "s-feed"})
    got = c.get("/api/profile", headers={"X-Session-Id": "s-feed"}).json()["profile"]
    assert got["stage"] == "extension" and got["sector"] == "textile" and got["funding_instrument"] == "grant"


def test_service_down_gives_clear_503():
    old = settings.bp_service_url
    settings.bp_service_url = "http://127.0.0.1:9"
    try:
        r = _client().post("/api/bp/questionnaire", json={"lang": "en"})
        assert r.status_code == 503 and "business-plan service" in r.text
    finally:
        settings.bp_service_url = old


def test_questionnaire_prefills_from_orchestrator(bp_service):
    sp.clear("s-q")
    sp.merge("s-q", {"stage": "creation", "sector": "bois", "legal_form": "SUARL"})
    r = _client().post("/api/bp/questionnaire", json={"lang": "fr", "answers": {"problem": "x"}}, headers={"X-Session-Id": "s-q"})
    q = {x["id"]: x for x in r.json()["questions"]}
    assert q["sector"]["status"] == "prefilled" and q["sector"]["value"] == "bois"
    assert q["problem"]["status"] == "answered"


def test_upload_and_questionnaire_together(bp_service):
    sp.clear("s-run")
    sp.merge("s-run", {"stage": "creation", "sector": "software"})
    plan = ("Plan de financement\nEmplois   Montant   Ressources   Montant\nInvestissements matériels   70 000   Fonds propres   40 000\n"
            "Total emplois   70 000   Total ressources   90 000\n").encode()
    c = _client()
    r = c.post("/api/bp/run", headers={"X-Session-Id": "s-run"},
               data={"mode": "review", "lang": "en", "answers": json.dumps({"stage": "extension", "problem": "Clinics lose time."})},
               files={"file": ("plan.txt", plan, "text/plain")})
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {s["kind"] for s in body["response"]["signals"]}
    assert "sources_neq_uses" in kinds and "profile_conflict" in kinds
    rep = body["report"]
    assert set(rep["input"]["methods"]) == {"upload", "questionnaire", "orchestrator_profile"}
    assert rep["context"]["provenance"]["sector"] == "orchestrator" and rep["context"]["provenance"]["stage"] == "questionnaire"
    docx = next(a for a in body["response"]["artifacts"] if a["kind"] == "docx")
    dl = c.get(f"/api/files/{docx['file_ref']}?kind=docx&name=review")
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    assert c.get("/api/files/..%2f..%2fetc%2fpasswd?kind=docx").status_code in (404, 422)
    # what the founder confirmed is now shared with the other tabs
    assert c.get("/api/profile", headers={"X-Session-Id": "s-run"}).json()["profile"]["stage"] == "extension"


def test_chat_turn_uses_orchestrator_profile(bp_service):
    sp.clear("s-chat")
    sp.merge("s-chat", {"sector": "bois"})
    c = _client()
    r = c.post("/api/bp/chat", json={"lang": "en"}, headers={"X-Session-Id": "s-chat"})
    assert r.status_code == 200 and r.json()["asking"] == "project_name"
    assert any("bois" in m for m in r.json()["messages"])
    r2 = c.post("/api/bp/chat", json={"lang": "en", "state": r.json()["state"], "message": "Atelier Nour"}, headers={"X-Session-Id": "s-chat"})
    assert r2.json()["answers"]["project_name"] == "Atelier Nour"


def test_bad_inputs_are_rejected_cleanly(bp_service):
    c = _client()
    assert c.post("/api/bp/run", data={"answers": "[1,2]"}).status_code == 422
    r = c.post("/api/bp/run", data={"mode": "nope", "answers": json.dumps({"sector": "a"})})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_INPUT"
    r = c.post("/api/bp/run", files={"file": ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 40, "application/msword")})
    assert r.status_code == 415
