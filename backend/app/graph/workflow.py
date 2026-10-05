"""Run one question through intake, routing, workers, verification, and composition.

The deck caps this at a router, domain workers, and one verifier, with at most
one extra search. Fraud review and aid matching are extra intents on the same
router. They are not extra agents in the legal RAG path.

Replace `run_question` with a LangGraph graph that writes the same ChatResponse.
"""

from app.modules.composer.answer import collect_drafts, compose
from app.modules.domains import WORKERS
from app.modules.intake.language import detect_language
from app.modules.rag.generation.grounded import draft_from_passages
from app.modules.rag.retrieval.hybrid import retrieve
from app.modules.router.domain_router import route_query
from app.modules.verifier.abstention import ABSTAIN_WHEN_NO_PASSAGES
from app.modules.verifier.citations import check_citations
from app.modules.verifier.claims import check_claims
from app.schemas.chat import ChatResponse
from app.schemas.common import ModuleStatus, TraceStep


def run_question(question: str) -> ChatResponse:
    language = detect_language(question)
    decision = route_query(question)
    trace = [
        TraceStep(
            module="intake.language",
            status=ModuleStatus.ok,
            detail=f"Language hint: {language}.",
        ),
        TraceStep(
            module="router",
            status=ModuleStatus.ok,
            detail=decision.detail,
        ),
    ]

    if decision.intent == "fraud":
        trace.append(
            TraceStep(
                module="fraud",
                status=ModuleStatus.placeholder,
                detail="Use the fraud-review form to upload the document. Chat does not score files.",
            )
        )
        return ChatResponse(
            status=ModuleStatus.placeholder,
            intent="fraud",
            domains=[],
            language=language,
            needs_clarification=False,
            answer=(
                "Fraud review reads an uploaded document. Open the Fraud review "
                "tab and attach the invoice, statement, or application. "
                "Scoring is not connected yet."
            ),
            abstained=True,
            citations=[],
            trace=trace,
        )

    if decision.intent == "aid":
        trace.append(
            TraceStep(
                module="aid",
                status=ModuleStatus.ok,
                detail="Use the aid form so stage and need are explicit.",
            )
        )
        return ChatResponse(
            status=ModuleStatus.placeholder,
            intent="aid",
            domains=[],
            language=language,
            needs_clarification=False,
            answer=(
                "Aid matching uses the company stage, sector, and need. "
                "Open the Aid and financing tab. The catalog can list local "
                "BFPME and business-plan files. It does not decide eligibility."
            ),
            abstained=False,
            citations=[],
            trace=trace,
        )

    passages, retrieval_step = retrieve(question, decision.domains)
    trace.append(retrieval_step)
    drafts = collect_drafts(WORKERS, question, decision.domains)
    for draft in drafts:
        trace.append(
            TraceStep(
                module=f"domains.{draft.domain}",
                status=draft.status,
                detail=draft.summary,
            )
        )
    trace.append(draft_from_passages(question, passages))
    claims = [claim for draft in drafts for claim in draft.claims]
    trace.append(check_claims(claims))
    trace.append(check_citations([]))
    answer, abstained, composer_step = compose(
        needs_clarification=decision.needs_clarification,
        domains=decision.domains,
        drafts=drafts,
    )
    if not passages and ABSTAIN_WHEN_NO_PASSAGES and not decision.needs_clarification:
        abstained = True
    trace.append(composer_step)

    return ChatResponse(
        status=ModuleStatus.placeholder,
        intent="rag",
        domains=decision.domains,
        language=language,
        needs_clarification=decision.needs_clarification,
        answer=answer,
        abstained=abstained,
        citations=[],
        trace=trace,
    )
