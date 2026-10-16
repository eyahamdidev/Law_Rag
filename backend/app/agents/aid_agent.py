"""Aid and grants specialist agent for Tunisian founders.

Matches founder profiles deterministically against Tunisian aid programs,
generates grounded checklist explanations, and detects legal statute handoffs.
"""

from app.agents.base import Agent
from app.modules.aid.explainer import explain_match
from app.modules.aid.extractor import extract_profile
from app.modules.aid.matcher import match
from app.modules.aid.rules_engine import detect_law_handoff
from app.schemas.agents import AgentCard, AgentRequest, AgentResult
from app.schemas.aid import AidProfile
from app.schemas.common import ModuleStatus, TraceStep
from app.schemas.rag import Passage


class AidAgent(Agent):
    """Specialist agent for Tunisian grants, loans, and aid programs."""

    def __init__(self, card: AgentCard) -> None:
        self.card = card

    def run(self, request: AgentRequest) -> AgentResult:
        trace: list[TraceStep] = []

        # 1. Check for statute handoff to Law (P1)
        handoff = detect_law_handoff(request.question)
        if handoff:
            trace.append(
                TraceStep(
                    module="agent.grants.handoff",
                    status=ModuleStatus.ok,
                    detail=f"Statute inquiry detected in aid agent; delegating legal explanation to {handoff.to}.",
                )
            )
            return AgentResult(
                agent=self.id,
                status="ok",
                answer=(
                    f"Votre question concerne le texte juridique officiel ({handoff.question}). "
                    "Cette analyse relève du spécialiste juridique (Law / P1)."
                ),
                citations=[],
                claims=[],
                passages=[],
                missing_info=[],
                trace=trace,
            )

        # 2. Extract and merge profile facts from question
        existing_profile = AidProfile(
            stage=request.profile.stage or "unspecified",
            sector=request.profile.sector or "",
            funding_need_tnd=request.profile.funding_need_tnd,
            governorate=request.profile.governorate,
            is_innovative=request.profile.has_startup_label or None,
            has_startup_label=request.profile.has_startup_label or None,
            is_graduate=request.profile.is_graduate or None,
            free_text=request.question,
        )

        extracted_profile, missing_fields, extractor_ref = extract_profile(
            request.question, known_profile=existing_profile
        )
        trace.append(
            TraceStep(
                module="agent.grants.intake",
                status=ModuleStatus.ok,
                detail=f"Profile extracted via {extractor_ref} (missing: {missing_fields or 'none'}).",
            )
        )

        # 3. Deterministic rule matching
        match_resp = match(extracted_profile)
        trace.extend(match_resp.trace)

        # 4. Generate grounded explanation
        answer, citations, claims, explainer_ref = explain_match(
            question=request.question,
            match_response=match_resp,
            language=request.language or "fr",
        )
        trace.append(
            TraceStep(
                module="agent.grants.explanation",
                status=ModuleStatus.ok,
                detail=f"Drafted grounded response via {explainer_ref} with {len(citations)} source citations.",
            )
        )

        # Convert citations into Passage objects for verifier
        passages = [
            Passage(
                chunk_id=f"aid:{c.ref}",
                doc_id=c.doc_id,
                title=c.title,
                path=c.path,
                corpora=["grants"],
                domain="grants",
                language=request.language or "fr",
                page_start=c.page,
                page_end=c.page,
                text=c.quote,
                score=1.0,
                score_kind="rule",
            )
            for c in citations
        ]

        # Profile updates discovered during this turn
        profile_updates = {}
        if extracted_profile.sector:
            profile_updates["sector"] = extracted_profile.sector
        if extracted_profile.stage != "unspecified":
            profile_updates["stage"] = extracted_profile.stage
        if extracted_profile.funding_need_tnd:
            profile_updates["funding_need_tnd"] = extracted_profile.funding_need_tnd

        status = "ok" if match_resp.programs else ("needs_info" if missing_fields else "ok")

        return AgentResult(
            agent=self.id,
            status=status,
            answer=answer,
            claims=claims,
            citations=citations,
            passages=passages,
            missing_info=missing_fields,
            profile_updates=profile_updates,
            confidence=1.0 if match_resp.programs else 0.5,
            trace=trace,
        )
