"""Contracts that must hold without API keys or a vector index.

The LLM is disabled (or faked) and retrieval runs on BM25 only, so these
tests run in CI and while an embedding job holds the local Qdrant folder.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.modules.rag.ingestion.pipeline import load_chunks

client = TestClient(create_app())
HAS_INDEX = bool(load_chunks("structural"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "retrieval_mode", "bm25")
    monkeypatch.setattr(settings, "use_reranker", False)


def test_health_modules_and_agents():
    assert client.get("/api/health").json()["status"] == "ok"
    ids = {item["id"] for item in client.get("/api/modules").json()}
    assert {"orchestrator.plan", "rag.retrieval", "agent.legal", "agent.grants"} <= ids
    agents = {item["id"] for item in client.get("/api/agents").json()}
    assert agents == {"legal", "grants", "business_plan", "marketing", "fraud"}


def test_corpus_sees_local_folders():
    body = client.get("/api/corpus").json()
    assert body["law"]["pdf_count"] > 0
    assert body["aid"]["file_count"] > 0


def test_every_prompt_renders():
    from app.prompts.library import all_prompts, get_prompt

    values = {k: "x" for k in (
        "agent_cards", "profile", "history", "attachments", "question", "domain", "language", "language_name",
        "task", "passages", "claims", "agent_answers", "missing_info", "unsupported", "partial", "payload", "instruction", "document_text",
    )}
    for spec in all_prompts():
        for version in spec["versions"]:
            messages = get_prompt(spec["id"], version["version"]).messages(**values)
            assert messages and "{{" not in messages[-1]["content"]


def test_keyword_router():
    from app.orchestrator.keyword_router import keyword_route

    assert "legal" in keyword_route("Quel est le capital minimum d'une SARL ?")
    assert "grants" in keyword_route("Comment obtenir un crédit BFPME ?")
    assert keyword_route("bonjour") == []


def test_broken_font_decoder():
    from app.modules.rag.ingestion.extract import _decode_broken

    assert _decode_broken("-RXUQDO\x032IILFLHO") == "Journal Officiel"
    assert _decode_broken("5pSXEOLTXH") == "République"


def test_structural_chunking_keeps_articles_and_acts():
    from pathlib import Path

    from app.modules.rag.ingestion.chunking import chunk_fixed, chunk_structural
    from app.modules.rag.ingestion.extract import PageText
    from app.modules.rag.ingestion.sources import SourceDocument

    doc = SourceDocument(doc_id="t:doc", path=Path(__file__), title="Test", corpora=["law"], domain="x", sha256="0")
    text = "Loi n° 2018-20 du 17 avril 2018, relative aux startups.\n" + "\n".join(
        f"Article {n} - Disposition numéro {n}. " + "texte " * 40 for n in range(1, 6)
    )
    pages = [PageText(page=1, text=text, needs_ocr=False, source="text")]
    chunks = chunk_structural(doc, pages)
    assert [c.article for c in chunks if c.article] == ["1", "2", "3", "4", "5"]
    assert all(c.act == "Loi n° 2018-20" for c in chunks if c.article)
    assert chunks[1].embed_text.startswith("Test — Loi n° 2018-20 — Article 1")
    assert all(c.article is None for c in chunk_fixed(doc, pages))


def test_bm25_tokenizer_folds_accents_and_arabic():
    from app.modules.rag.retrieval.bm25 import tokenize

    assert tokenize("Société") == tokenize("societe")
    assert tokenize("المؤسسة") == tokenize("المؤسسه")


def test_composer_renumbers_and_drops_unsupported():
    from app.orchestrator.composer import _renumber
    from app.schemas.agents import AgentResult

    result = AgentResult(agent="legal", status="ok", answer="A [1]. B [2]. C [1, 3].")
    assert _renumber(result, {1: 4, 3: 5}) == "A [4]. B . C [4, 5]."


def test_planner_validates_llm_output(monkeypatch):
    from app.orchestrator import planner
    from app.schemas.agents import FounderProfile

    class FakeLLM:
        available = True

        def chat_json(self, messages, **kwargs):
            data = {
                "language": "en",
                "steps": [
                    {"agent": "legal", "task": "t", "search_query": "SARL capital"},
                    {"agent": "astrology", "task": "t"},
                    {"agent": "legal", "task": "duplicate"},
                ],
                "profile_updates": {"sector": "fintech"},
            }
            return data, type("R", (), {"provider": "fake", "model": "m"})()

    monkeypatch.setattr(planner, "get_llm", lambda: FakeLLM())
    plan = planner.make_plan("What capital for a SARL?", [], FounderProfile(), [])
    assert [s.agent for s in plan.steps] == ["legal"]
    assert plan.source == "llm" and plan.profile_updates == {"sector": "fintech"}


def test_chat_asks_for_clarification_when_vague():
    body = client.post("/api/chat", json={"question": "bonjour"}).json()
    assert body["needs_clarification"] is True
    assert body["plan"]["source"] == "keyword"
    assert body["citations"] == []


@pytest.mark.skipif(not HAS_INDEX, reason="run the ingestion pipeline first")
def test_chat_offline_returns_evidence_and_keeps_session():
    first = client.post("/api/chat", json={"question": "Quel est le capital minimum d'une société anonyme ?"}).json()
    assert first["plan"]["steps"][0]["agent"] == "legal"
    assert first["citations"], first["trace"]
    assert all(c["path"].endswith(".pdf") for c in first["citations"])
    second = client.post("/api/chat", json={"question": "Et pour une SARL ?", "session_id": first["session_id"]}).json()
    assert second["session_id"] == first["session_id"]


@pytest.mark.skipif(not HAS_INDEX, reason="run the ingestion pipeline first")
def test_search_endpoint_filters_by_corpus():
    body = client.post("/api/search", json={"query": "FONAPRAM crédit", "corpora": ["grants"], "k": 3}).json()
    assert body["passages"]
    assert all("grants" in p["corpora"] for p in body["passages"])


def test_aid_creation_lists_bfpme():
    body = client.post("/api/aid/match", json={"stage": "creation", "need": "financing"}).json()
    ids = {item["id"] for item in body["programs"]}
    assert "bfpme-creation" in ids


def test_fraud_upload_hashes_without_a_risk_level():
    response = client.post(
        "/api/fraud/analyze",
        files={"file": ("facture.txt", b"total 1000", "text/plain")},
        data={"document_type": "invoice"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["risk_level"] == "unknown"
    assert len(body["document_hash"]) == 64


def test_guardrail_removes_uncited_facts_and_keeps_the_rest():
    from app.orchestrator.guardrails import drop_uncited

    # Shape of the real fintech answer of 2026-10-12, where composer v2 let an uncited fact through.
    answer = "\n".join([
        "**Legal form for a fintech startup**",
        "- A société anonyme (SA) is the default form for financial activities.",
        "- A SUARL is allowed for any commercial purpose (à vérifier) [3].",
        "",
        "## Funding options",
        "You can access several public instruments:",
        "- AIR supports a first version of an innovative solution [2].",
        "These programmes are open to innovative startups, including fintech.",
        "Sentence without marker. Sentence with marker [1].",
        "",
        "## Banking",
        "Banks must offer basic services.",
        "",
        "I could not find the answer for this topic.",
        "- Quel est votre secteur ?",
    ])
    text, removed = drop_uncited(answer)

    assert "default form" not in text and "open to innovative startups" not in text
    assert "Banks must offer" not in text
    assert "## Banking" in text  # the "could not find" notice below it is still content
    assert "SUARL is allowed" in text and "AIR supports" in text
    assert "Sentence without marker. Sentence with marker [1]." in text  # paragraph-level: kept
    assert "**Legal form for a fintech startup**" in text and "## Funding options" in text
    assert "You can access several public instruments:" in text
    assert "I could not find the answer" in text and "Quel est votre secteur ?" in text
    assert len(removed) == 3


def test_guardrail_keeps_arabic_cited_paragraph_and_notice():
    from app.orchestrator.guardrails import drop_uncited

    text, removed = drop_uncited("عطلة لمدة سنة قابلة للتمديد مرة واحدة [2].\nلم أجد معلومات عن هذا الموضوع.\nيمنح القانون امتيازات جبائية.")
    assert "[2]" in text and "لم أجد" in text
    assert removed == ["يمنح القانون امتيازات جبائية."]


def test_guardrail_drops_a_heading_left_without_content():
    from app.orchestrator.guardrails import drop_uncited

    text, _ = drop_uncited("## Tax\nCompanies pay 20%.\n\n## Funding\n- AIR grant [1].")
    assert "## Tax" not in text and text == "## Funding\n- AIR grant [1]."


class _FakeLLM:
    available = True

    def __init__(self, data):
        self.data = data

    def chat_json(self, messages, **kwargs):
        return self.data, type("R", (), {"provider": "fake", "model": "m"})()


def _fraud_request(question="Check this invoice", **kw):
    from app.schemas.agents import AgentRequest

    return AgentRequest(task="check", question=question, language="fr", session_id=None, **kw)


def test_fraud_answer_is_written_from_the_service_fields_only():
    from app.agents.fraud_agent import describe

    text = describe({
        "risk_score": 81, "risk_level": "HIGH_RISK", "requires_human_review": True, "data_coverage": "HIGH",
        "signals": [{"signal": "duplicate_invoice", "severity": "high", "detail": "The same payment of 1250 TND appears 2 times."}],
    }, "fr")
    assert "élevé (81/100)" in text and "1250 TND appears 2 times" in text
    assert "ni une probabilité ni une preuve" in text


def test_fraud_agent_routes_contracts_and_missing_amounts_without_calling_the_service(monkeypatch):
    from app.agents import fraud_agent
    from app.agents.registry import FRAUD

    agent = fraud_agent.FraudAgent(FRAUD)
    monkeypatch.setattr(fraud_agent, "get_llm", lambda: _FakeLLM({"kind": "contract", "amount": None}))
    assert agent.run(_fraud_request("Ce contrat est-il équitable ?")).status == "abstained"
    monkeypatch.setattr(fraud_agent, "get_llm", lambda: _FakeLLM({"kind": "invoice", "amount": None}))
    result = agent.run(_fraud_request())
    assert result.status == "needs_info" and result.missing_info


def test_fraud_agent_reports_a_stopped_service(monkeypatch):
    from app.agents import fraud_agent
    from app.agents.registry import FRAUD

    monkeypatch.setattr(settings, "fraud_service_url", "http://127.0.0.1:9")  # nothing listens there
    monkeypatch.setattr(fraud_agent, "get_llm", lambda: _FakeLLM({"kind": "invoice", "amount": 1250, "currency": "TND"}))
    result = fraud_agent.FraudAgent(FRAUD).run(_fraud_request())
    assert result.status == "error" and "8100" in result.answer


def test_fraud_transaction_maps_mobile_money_to_the_mobile_channel():
    from app.agents.fraud_agent import build_transaction

    tx = build_transaction({"amount": 300, "counterparty_name": "Ali Shop", "payment_method": "mobile_money", "date": "2026-10-01"}, _fraud_request())
    assert tx["channel"] == "mobile" and tx["receiver_id"] == "ali-shop" and tx["timestamp"] == "2026-10-01T12:00:00"


def test_composer_keeps_tool_output_verbatim_next_to_cited_answers():
    from app.orchestrator.composer import compose
    from app.orchestrator.planner import Plan
    from app.schemas.agents import AgentResult, Citation
    from app.schemas.rag import Passage

    passage = Passage(chunk_id="c", doc_id="d", title="T", path="p.pdf", corpora=["law"], domain="x", language="fr",
                      page_start=1, page_end=1, text="t", score=1.0, score_kind="rrf")
    legal = AgentResult(agent="legal", status="ok", answer="Une SARL a deux associés [1].", passages=[passage],
                        citations=[Citation(ref=1, doc_id="d", title="T", path="p.pdf", page=1, quote="t")])
    fraud = AgentResult(agent="fraud", status="ok", answer="Niveau de risque : faible (6/100).\nAucun signal de fraude.")
    text, citations, abstained, how = compose("q", Plan(language="fr"), [legal, fraud])
    assert "Aucun signal de fraude." in text and "deux associés [1]" in text
    assert "tool output" in how and not abstained and len(citations) == 1


def test_composer_shows_an_agents_own_reason_for_not_answering():
    from app.orchestrator.composer import compose
    from app.orchestrator.planner import Plan
    from app.schemas.agents import AgentResult

    reason = "La vérification de l'équité d'un contrat n'est pas encore disponible."
    text, _, abstained, _ = compose("q", Plan(language="fr"), [AgentResult(agent="fraud", status="abstained", answer=reason)])
    assert text == reason and abstained
    text, _, _, _ = compose("q", Plan(language="fr"), [AgentResult(agent="grants", status="abstained", answer="")])
    assert text.startswith("Je n'ai pas trouvé")


def test_fraud_ids_fold_accents():
    from app.agents.fraud_agent import _slug

    assert _slug("Fournisseur Médina Services", "x") == "fournisseur-medina-services"


def _bp_request(attachments=(), **kw):
    from app.schemas.agents import AgentRequest, FounderProfile

    return AgentRequest(task="review", question="Relis mon plan", language="fr", attachments=list(attachments),
                        profile=FounderProfile(employees=4, funding_need_tnd=80000, legal_form="SARL"), **kw)


def _plan_attachment():
    import base64
    from app.schemas.agents import Attachment

    return Attachment(filename="plan.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      data_base64=base64.b64encode(b"fake docx").decode())


def test_business_plan_agent_asks_for_a_plan_instead_of_reviewing_the_question():
    from app.agents.business_plan_agent import BusinessPlanAgent
    from app.agents.registry import BUSINESS_PLAN

    result = BusinessPlanAgent(BUSINESS_PLAN).run(_bp_request())
    assert result.status == "needs_info" and "joignez" in result.answer


def test_business_plan_agent_shows_the_service_findings_and_report(monkeypatch, tmp_path):
    from app.agents import business_plan_agent as bpa
    from app.agents.registry import BUSINESS_PLAN

    monkeypatch.setattr(settings, "uploads_dir", tmp_path)
    sent = {}

    def fake_run(**kw):
        sent.update(kw)
        return 200, {"status": "ok", "answer": "Complétude du plan : 18/100.",
                     "signals": [{"severity": "high", "message": "Review this: Pressure to commit quickly."},
                                 {"severity": "info", "message": "minor"}],
                     "artifacts": [{"kind": "docx", "file_ref": "ab" * 32, "label": "bp_review"}], "trace": [],
                     "handoff": {"to": "aid", "question": "q"}}

    monkeypatch.setattr(bpa.client, "run", fake_run)
    result = bpa.BusinessPlanAgent(BUSINESS_PLAN).run(_bp_request([_plan_attachment()]))
    assert result.status == "ok" and "18/100" in result.answer and "Pressure to commit" in result.answer
    assert "minor" not in result.answer and f"/api/files/{'ab' * 32}?kind=docx" in result.answer
    assert sent["profile"]["headcount"] == 4 and sent["profile"]["funding_amount"] == 80000
    assert "le financement et les aides" in result.answer and ": aid" not in result.answer
    assert (tmp_path / sent["file_ref"]).read_bytes() == b"fake docx"


def test_business_plan_agent_reports_a_stopped_service(monkeypatch, tmp_path):
    from app.agents.business_plan_agent import BusinessPlanAgent
    from app.agents.registry import BUSINESS_PLAN

    monkeypatch.setattr(settings, "uploads_dir", tmp_path)
    monkeypatch.setattr(settings, "bp_service_url", "http://127.0.0.1:9")
    result = BusinessPlanAgent(BUSINESS_PLAN).run(_bp_request([_plan_attachment()]))
    assert result.status == "error" and "8104" in result.answer


def test_restore_markers_gives_back_citations_the_rewrite_lost():
    """Observed: the composer rewrote a cited BFPME list without its [n]; the guardrail then deleted it."""
    from app.orchestrator.guardrails import drop_uncited, restore_markers

    agent = (
        "Le dossier doit contenir :\n"
        "- La demande de financement signée [2];\n"
        "- Les photocopies de la CIN du promoteur et des associés [2];\n"
        "- Les informations générales de l'entreprise [1]."
    )
    composed = (
        "## Documents requis\n"
        "- La **demande de financement signée** ;\n"
        "- Les photocopies de la CIN du promoteur et des associés.\n"
        "- Un apport personnel de 30 % est exigé.\n"
        "- Les informations générales de l'entreprise [1]."
    )
    text, restored = restore_markers(composed, [agent])
    assert restored == 2
    assert "- La **demande de financement signée** [2];" in text
    assert "- Les photocopies de la CIN du promoteur et des associés [2]." in text
    final, removed = drop_uncited(text)
    assert removed == ["- Un apport personnel de 30 % est exigé."]  # new content: no cited line restates it
    assert final.count("[2]") == 2 and "[1]" in final


def test_guardrail_keeps_legal_evidence_only_excerpts():
    """Raw excerpts (legal agent fallback) were reduced to "[1] Article 225 :" headers by the guardrail."""
    from app.agents.legal_guidance.engine import _evidence_only
    from app.orchestrator.guardrails import drop_uncited
    from app.schemas.rag import Passage

    passage = Passage(chunk_id="c", doc_id="law:x", title="Loi", path="p", corpora=["law"], domain="company_law", language="fr",
                      page_start=19, page_end=19, article="161", text="Article 161 :\nLe capital social ne peut être\ninférieur à 50.000 dinars.",
                      score=1.0, score_kind="rerank")
    result = _evidence_only([passage], "fr", [])
    text, removed = drop_uncited(result.answer)
    assert removed == []
    assert "[1] Article 161 : Le capital social ne peut être inférieur à 50.000 dinars." in text
    assert text.startswith("Voici les passages dans leur langue originale")
