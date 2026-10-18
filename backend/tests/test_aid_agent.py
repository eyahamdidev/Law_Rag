"""Unit and integration tests for AidAgent, profile extractor, and explainer."""

from app.agents.aid_agent import AidAgent
from app.agents.registry import GRANTS
from app.modules.aid.explainer import explain_match
from app.modules.aid.extractor import extract_profile, heuristic_extract_profile
from app.modules.aid.matcher import match
from app.schemas.agents import AgentRequest, FounderProfile
from app.schemas.aid import AidProfile


def test_heuristic_extractor_multilingual():
    """Extract profile fields accurately without external LLM."""
    # French
    p_fr = heuristic_extract_profile("Je veux créer une entreprise dans l'industrie avec un crédit de 300 000 DT à Kasserine.")
    assert p_fr.stage == "creation"
    assert p_fr.sector == "industrie"
    assert p_fr.need == "loan"
    assert p_fr.funding_need_tnd == 300000.0
    assert p_fr.governorate == "kasserine"

    # Arabic
    p_ar = heuristic_extract_profile("توسعة معمل في قطاع الصناعات الغذائية بالقصرين بمبلغ 500 ألف دينار")
    assert p_ar.stage == "extension"
    assert p_ar.sector == "agroalimentaire"
    assert p_ar.governorate == "kasserine"

    # English
    p_en = heuristic_extract_profile("We are looking for a grant for our green tech and solar energy project.")
    assert p_en.need == "grant"
    assert p_en.sector == "greentech"


def test_extractor_flags_missing_fields_when_vague():
    """Missing key fields like sector or stage are flagged."""
    profile, missing, ref = extract_profile("Bonjour, je cherche de l'aide.")
    assert "stage" in missing or profile.stage == "unspecified"
    assert "sector" in missing or not profile.sector
    assert ref


def test_explainer_produces_grounded_citations():
    """Explainer produces citations referencing official sources with quotes."""
    profile = AidProfile(stage="creation", sector="software", need="financing", is_innovative=True)
    match_resp = match(profile)
    answer, citations, claims, ref = explain_match("financement startup", match_resp, language="fr")

    assert len(citations) > 0
    assert len(claims) > 0
    # Each programme cites the indexed page of its source (law: or grants:), or catalog:<id>
    # when no index is built; nothing is marked supported before the verifier runs.
    rule_citations = citations[: len(match_resp.programs)]
    assert all(c.doc_id.split(":")[0] in {"grants", "law", "catalog"} for c in rule_citations)
    assert all(c.supported is None for c in rule_citations)
    assert all(c.verdict == "unchecked" for c in claims)
    assert all(c.path for c in citations)
    assert all(c.page is not None for c in citations)
    assert ref


def test_aid_agent_statute_handoff():
    """Aid agent hands off legal statute questions directly to Law (P1)."""
    agent = AidAgent(GRANTS)
    req = AgentRequest(
        task="Check grants",
        question="Que dit l'article 6 de la loi 2016-71 sur l'investissement ?",
        language="fr",
        profile=FounderProfile(),
    )
    res = agent.run(req)
    assert res.agent == "grants"
    assert res.status == "ok"
    assert "juridique" in res.answer.lower()
    assert any("handoff" in step.module for step in res.trace)


def test_aid_agent_full_flow():
    """Aid agent executes full pipeline: intake, matching, explanation, profile updates."""
    agent = AidAgent(GRANTS)
    req = AgentRequest(
        task="Find funding",
        question="Je crée une startup logicielle innovante à Tunis avec un besoin de 200 000 DT.",
        language="fr",
        profile=FounderProfile(),
    )
    res = agent.run(req)
    assert res.agent == "grants"
    assert res.status == "ok"
    assert len(res.citations) > 0
    assert res.profile_updates.get("stage") == "creation"
    assert res.profile_updates.get("sector") == "technologie"
    assert any(step.module == "agent.grants.explanation" for step in res.trace)



def test_general_grants_question_falls_back_to_rag(monkeypatch):
    """No founder facts and no eligibility request: the cited RAG agent answers."""
    from app.schemas.agents import AgentResult

    agent = AidAgent(GRANTS)
    monkeypatch.setattr(agent.fallback, "run", lambda request: AgentResult(agent="grants", status="ok", answer="rag answer"))
    res = agent.run(AgentRequest(task="t", question="Que garantit la SOTUGAR ?", language="fr", profile=FounderProfile()))
    assert res.answer == "rag answer"
    assert res.trace[0].module == "agent.grants.route"


def test_eligibility_answer_marks_unverified_figures(monkeypatch):
    """Matched programmes show unsourced figures as 'to confirm' and carry one citation each."""
    import app.agents.aid_agent as aid_agent

    monkeypatch.setattr(aid_agent, "extract_profile", lambda q, known_profile: (heuristic_extract_profile(q), [], "heuristic"))
    agent = AidAgent(GRANTS)
    res = agent.run(AgentRequest(task="t", question="Je veux créer une entreprise dans l'industrie avec un crédit de 300 000 DT à Sfax.",
                                 language="fr", profile=FounderProfile()))
    assert "BFPME" in res.answer
    assert "À confirmer" in res.answer and "max_investment_tnd=15,000,000" in res.answer
    assert "100 000 et 15 000 000" not in res.answer
    assert not res.passages and len(res.citations) == res.answer.count("**") // 2


def test_early_stage_session_profile_does_not_crash(monkeypatch):
    """FounderProfile allows stage='early', AidProfile does not: it is read as creation."""
    import app.agents.aid_agent as aid_agent

    seen = {}
    def fake_extract(question, known_profile):
        seen["stage"] = known_profile.stage
        return known_profile, [], "fake"
    monkeypatch.setattr(aid_agent, "extract_profile", fake_extract)
    AidAgent(GRANTS).run(AgentRequest(task="t", question="Quel programme me convient ?", language="fr",
                                      profile=FounderProfile(stage="early", sector="software")))
    assert seen["stage"] == "creation"


def test_composer_keeps_tool_citations():
    """A tool answer (no passages) is shown verbatim with its citations."""
    from app.orchestrator.composer import compose
    from app.orchestrator.planner import Plan
    from app.schemas.agents import AgentResult, Citation

    citation = Citation(ref=1, doc_id="grants:checklist-creation-entreprise", title="t", path="p", page=1, quote="q")
    result = AgentResult(agent="grants", status="ok", answer="BFPME [1]", citations=[citation])
    text, citations, abstained, how = compose("q", Plan(language="fr"), [result])
    assert text == "BFPME [1]" and len(citations) == 1 and how == "tool output, verbatim"
