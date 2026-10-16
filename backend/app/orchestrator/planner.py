"""Planner: which agents, with which sub-task, or a clarifying question.

LLM planner (prompt orchestrator.planner) first; the keyword router when the
LLM is unreachable or its plan is unusable. The plan is validated in code:
unknown agent ids are dropped, at most three steps are kept, and a missing
search query falls back to the founder's message.
"""

from dataclasses import dataclass, field

from app.agents.registry import AGENTS, cards_for_prompt
from app.modules.intake.language import detect_language
from app.orchestrator.keyword_router import keyword_route
from app.prompts.library import get_prompt
from app.schemas.agents import Attachment, FounderProfile, Turn
from app.services.llm import LLMUnavailable, get_llm

MAX_STEPS = 3


@dataclass
class PlanStep:
    agent: str
    task: str
    search_query: str


@dataclass
class Plan:
    language: str
    steps: list[PlanStep] = field(default_factory=list)
    clarification: str | None = None
    out_of_scope: bool = False
    profile_updates: dict = field(default_factory=dict)
    reason: str = ""
    source: str = "llm"  # llm or keyword
    prompt_ref: str | None = None
    error: str | None = None


def _history_text(history: list[Turn], limit: int = 6) -> str:
    turns = history[-limit:]
    return "\n".join(f"{t.role}: {t.content[:400]}" for t in turns) or "(first message)"


def _attachments_text(attachments: list[Attachment]) -> str:
    if not attachments:
        return "none"
    return "; ".join(f"{a.filename} ({a.mime}, {len(a.text)} chars extracted by {a.extraction})" for a in attachments)


def keyword_plan(question: str, language: str, error: str | None = None) -> Plan:
    agents = keyword_route(question)[:MAX_STEPS]
    clarification = None
    if not agents:
        clarification = {
            "fr": "Pouvez-vous préciser votre besoin : forme juridique et lois, financement et aides, business plan, marketing, ou vérification d'un document ?",
            "ar": "هل يمكنك توضيح حاجتك: الإطار القانوني، التمويل والمنح، مخطط الأعمال، التسويق، أو التثبت من وثيقة؟",
            "en": "Could you say what you need: legal form and law, funding and grants, business plan, marketing, or a document check?",
        }.get(language, "Could you say more about what you need?")
    return Plan(
        language=language,
        steps=[PlanStep(agent=a, task=question, search_query=question) for a in agents],
        clarification=clarification,
        reason="Keyword baseline: " + (", ".join(agents) if agents else "no agent term matched."),
        source="keyword",
        error=error,
    )


def make_plan(
    question: str,
    history: list[Turn],
    profile: FounderProfile,
    attachments: list[Attachment],
) -> Plan:
    language = detect_language(question)
    llm = get_llm()
    if not llm.available:
        return keyword_plan(question, language, error="no LLM configured")

    prompt = get_prompt("orchestrator.planner")
    try:
        data, result = llm.chat_json(
            prompt.messages(
                agent_cards=cards_for_prompt(),
                profile=profile.known() or "nothing known yet",
                history=_history_text(history),
                attachments=_attachments_text(attachments),
                question=question,
            ),
            tier="fast",
            max_tokens=700,
        )
    except (LLMUnavailable, ValueError) as error:
        return keyword_plan(question, language, error=f"planner fallback: {str(error)[:200]}")

    steps = []
    for item in data.get("steps") or []:
        if not isinstance(item, dict) or item.get("agent") not in AGENTS:
            continue
        if any(s.agent == item["agent"] for s in steps):
            continue
        steps.append(
            PlanStep(
                agent=item["agent"],
                task=str(item.get("task") or question),
                search_query=str(item.get("search_query") or question),
            )
        )
    plan_language = data.get("language") if data.get("language") in {"fr", "ar", "en"} else language
    clarification = data.get("clarification") or None
    out_of_scope = bool(data.get("out_of_scope"))
    if not steps and not clarification and not out_of_scope:
        return keyword_plan(question, plan_language, error="planner returned an empty plan")
    return Plan(
        language=plan_language,
        steps=steps[:MAX_STEPS],
        clarification=clarification if not steps else None,
        out_of_scope=out_of_scope and not steps,
        profile_updates=data.get("profile_updates") if isinstance(data.get("profile_updates"), dict) else {},
        reason=str(data.get("reason") or ""),
        source="llm",
        prompt_ref=f"{prompt.ref} via {result.provider}/{result.model}",
    )
