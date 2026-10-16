"""Legal-only entry point for the existing cited RAG implementation."""

from app.agents.rag_agent import RagAgent
from app.schemas.agents import AgentCard
from app.schemas.agents import AgentRequest, AgentResult


class LegalGuidanceAgent(RagAgent):
    """Keep legal retrieval scoped to the law corpus, separate from grants."""

    def __init__(self, card: AgentCard) -> None:
        super().__init__(card, corpora=["law"], domain_label="Tunisian business law")

    def run(self, request: AgentRequest) -> AgentResult:
        if request.legal_contract is not None:
            from app.agents.contract_drafting.service import draft_contract
            from app.schemas.legal import DraftRequest
            payload = dict(request.legal_contract)
            from app.schemas.agents import FounderProfile
            supplied_profile = FounderProfile.model_validate(payload.get("profile") or {})
            payload["profile"] = {**request.profile.known(), **supplied_profile.known()}
            draft = draft_contract(DraftRequest.model_validate(payload))
            return AgentResult(agent="legal", status="needs_info" if draft.missing_fields else "ok",
                               answer="\n".join(m.question for m in draft.missing_fields) if draft.missing_fields else draft.title + " — " + draft.status,
                               missing_info=[m.question for m in draft.missing_fields],
                               artifacts=[{"kind": "contract_draft", "draft": draft.model_dump()}])
        from app.agents.legal_guidance.engine import guidance
        from app.schemas.legal import GuidanceRequest
        return guidance(GuidanceRequest(question=request.question, language=request.language if request.language in {"fr", "ar", "en"} else "fr",
                                        profile=request.profile, attachments=request.attachments)).result
