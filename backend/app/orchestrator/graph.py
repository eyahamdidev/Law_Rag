"""The orchestrator as a LangGraph state graph.

    plan --(clarify / out of scope)--------------------> compose -> END
         \\--Send per step--> run_agent (parallel) --> verify -> compose

Uploaded files are turned into Attachment text (PDF text, OCR or vision)
by app/modules/intake before the graph starts, so every node sees text.

Architecture: a router/planner with parallel workers and one verifier, not a
swarm. Agents never talk to each other; every hand-off goes through the state,
so each step is visible in the trace and testable alone. The only loop is the
one follow-up search inside a RAG agent, so a turn costs at most
1 (plan) + 2 per agent + 1 (verify) + 1 (compose) LLM calls.
"""

import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.registry import AGENTS
from app.orchestrator.composer import compose
from app.orchestrator.planner import Plan, PlanStep, make_plan
from app.orchestrator.sessions import store
from app.orchestrator.verifier import Verification, verify
from app.schemas.agents import AgentRequest, AgentResult, Attachment, FounderProfile, Turn
from app.schemas.chat import AgentSummary, ChatResponse, PlanOut, PlanStepOut
from app.schemas.common import ModuleStatus, TraceStep


class TurnState(TypedDict, total=False):
    question: str
    session_id: str
    history: list[Turn]
    profile: FounderProfile
    attachments: list[Attachment]
    legal_contract: dict | None
    plan: Plan
    step: PlanStep  # set only inside a run_agent branch
    results: Annotated[list[AgentResult], operator.add]
    verification: Verification
    answer: str
    citations: list
    abstained: bool
    composed_by: str
    trace: Annotated[list[TraceStep], operator.add]


def _plan(state: TurnState) -> dict:
    started = time.perf_counter()
    if state.get("legal_contract") is not None:
        plan = Plan(language=state["legal_contract"].get("language", "fr"),
                    steps=[PlanStep(agent="legal", task="Draft the requested agreement from confirmed structured terms", search_query=state["question"])],
                    reason="Explicit structured legal contract intake", source="structured_legal_intake")
    else:
        plan = make_plan(state["question"], state.get("history", []), state["profile"], state.get("attachments", []))
    profile, rejected = state["profile"].merge(plan.profile_updates)
    detail = f"{plan.source}: " + (
        ", ".join(s.agent for s in plan.steps) if plan.steps else ("clarify" if plan.clarification else "no agent")
    )
    detail += f". {plan.reason[:160]}" if plan.reason else ""
    if plan.error:
        detail += f" ({plan.error})"
    if rejected:
        detail += f" Rejected profile values: {', '.join(rejected)}."
    return {
        "plan": plan,
        "profile": profile,
        "trace": [TraceStep(module="orchestrator.plan", status=ModuleStatus.ok, detail=f"{detail} [{(time.perf_counter() - started) * 1000:.0f} ms]")],
    }


def _fan_out(state: TurnState):
    plan = state["plan"]
    if not plan.steps:
        return "compose"
    return [Send("run_agent", {**state, "step": step}) for step in plan.steps]


def _run_agent(state: TurnState) -> dict:
    step = state["step"]
    agent = AGENTS[step.agent]
    request = AgentRequest(
        task=step.task,
        search_query=step.search_query,
        question=state["question"],
        language=state["plan"].language,
        profile=state["profile"],
        attachments=state.get("attachments", []),
        history=state.get("history", []),
        legal_contract=state.get("legal_contract") if step.agent == "legal" else None,
        session_id=state.get("session_id"),
    )
    started = time.perf_counter()
    try:
        result = agent.run(request)
    except Exception as error:  # one failing agent must not sink the turn
        result = AgentResult(agent=step.agent, status="error", answer=f"The {agent.card.name} agent failed.")
        result.trace.append(TraceStep(module=f"agent.{step.agent}", status=ModuleStatus.skipped, detail=f"{type(error).__name__}: {str(error)[:200]}"))
    result.trace.append(
        TraceStep(module=f"agent.{step.agent}", status=ModuleStatus.ok, detail=f"{result.status} in {(time.perf_counter() - started) * 1000:.0f} ms")
    )
    return {"results": [result], "trace": result.trace}


def _verify(state: TurnState) -> dict:
    started = time.perf_counter()
    results = _ordered(state)
    report = verify(results)
    validity = report.citation_validity
    detail = (
        f"citations valid {report.citations_valid}/{report.citations_checked}; "
        f"claims {report.supported} supported, {report.partial} partial, {report.unsupported} unsupported "
        f"of {report.claims_total} ({report.claim_check}) [{(time.perf_counter() - started) * 1000:.0f} ms]"
    )
    status = ModuleStatus.ok if validity in (None, 1.0) else ModuleStatus.placeholder
    return {"verification": report, "trace": [TraceStep(module="orchestrator.verify", status=status, detail=detail)]}


def _ordered(state: TurnState) -> list[AgentResult]:
    order = {s.agent: i for i, s in enumerate(state["plan"].steps)}
    return sorted(state.get("results", []), key=lambda r: order.get(r.agent, 99))


def _compose(state: TurnState) -> dict:
    started = time.perf_counter()
    answer, citations, abstained, how = compose(state["question"], state["plan"], _ordered(state))
    return {
        "answer": answer,
        "citations": citations,
        "abstained": abstained,
        "composed_by": how,
        "trace": [TraceStep(module="orchestrator.compose", status=ModuleStatus.ok, detail=f"{how} [{(time.perf_counter() - started) * 1000:.0f} ms]")],
    }


def build_graph():
    graph = StateGraph(TurnState)
    graph.add_node("plan", _plan)
    graph.add_node("run_agent", _run_agent)
    graph.add_node("verify", _verify)
    graph.add_node("compose", _compose)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", _fan_out, ["run_agent", "compose"])
    graph.add_edge("run_agent", "verify")
    graph.add_edge("verify", "compose")
    graph.add_edge("compose", END)
    return graph.compile()


_graph = None


def run_turn(question: str, session_id: str | None = None, attachments: list[Attachment] | None = None, legal_contract: dict | None = None) -> ChatResponse:
    global _graph
    if _graph is None:
        _graph = build_graph()
    started = time.perf_counter()
    session = store.get(session_id)
    state = _graph.invoke(
        {
            "question": question,
            "session_id": session.session_id,
            "history": list(session.history),
            "profile": session.profile,
            "attachments": attachments or [],
            "legal_contract": legal_contract,
            "results": [],
            "trace": [],
        }
    )
    plan: Plan = state["plan"]
    results = _ordered(state)
    session.profile = state["profile"]
    session.add("user", question)
    session.add("assistant", state["answer"])
    store.save(session)
    report: Verification = state.get("verification") or Verification()
    any_real = any(r.status == "ok" for r in results)
    return ChatResponse(
        session_id=session.session_id,
        status=ModuleStatus.ok if any_real or plan.clarification else ModuleStatus.placeholder,
        language=plan.language,
        plan=PlanOut(
            source=plan.source,
            steps=[PlanStepOut(agent=s.agent, task=s.task, search_query=s.search_query) for s in plan.steps],
            reason=plan.reason,
            clarification=plan.clarification,
            out_of_scope=plan.out_of_scope,
            prompt_ref=plan.prompt_ref,
        ),
        answer=state["answer"],
        abstained=state["abstained"],
        needs_clarification=bool(plan.clarification and not plan.steps) or any(r.status == "needs_info" for r in results),
        citations=state["citations"],
        agents=[AgentSummary(agent=r.agent, status=r.status, answer=r.answer, missing_info=r.missing_info) for r in results],
        missing_info=list(dict.fromkeys(m for r in results for m in r.missing_info)),
        profile=session.profile,
        verification=report.as_dict(),
        composed_by=state.get("composed_by", ""),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        trace=state["trace"],
        artifacts=[artifact for result in results for artifact in result.artifacts],
    )
