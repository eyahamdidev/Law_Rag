"""Compose the reply: global citation numbers, verified content, open questions."""

import re

from app.agents.registry import AGENTS
from app.orchestrator.guardrails import drop_uncited, restore_markers
from app.orchestrator.planner import Plan
from app.orchestrator.verifier import _MARKER
from app.prompts.library import get_prompt
from app.schemas.agents import AgentResult, Citation
from app.services.llm import LLMUnavailable, get_llm

NOT_SCOPE = {
    "fr": "Je suis un assistant pour la création et la gestion d'entreprise en Tunisie (droit des affaires, financement, business plan, marketing). Cette question sort de ce cadre.",
    "ar": "أنا مساعد لبعث المؤسسات وتسييرها في تونس (القانون، التمويل، مخطط الأعمال، التسويق). هذا السؤال خارج هذا الإطار.",
    "en": "I help with starting and running a business in Tunisia (law, funding, business plan, marketing). This question is outside that scope.",
}
NOTHING_FOUND = {
    "fr": "Je n'ai pas trouvé de réponse fiable dans les textes disponibles. Pour une décision, consultez le texte officiel ou un professionnel (avocat, expert-comptable, conseiller BFPME/API).",
    "ar": "لم أجد إجابة موثوقة في النصوص المتوفرة. لاتخاذ قرار، يرجى الرجوع إلى النص الرسمي أو إلى مختص.",
    "en": "I could not find a reliable answer in the available texts. For a decision, check the official text or ask a professional (lawyer, accountant, BFPME/API adviser).",
}


def _renumber(result: AgentResult, mapping: dict[int, int]) -> str:
    def replace(match: re.Match) -> str:
        refs = [int(n) for n in re.split(r"\s*[,;]\s*", match.group(1))]
        kept = [str(mapping[r]) for r in refs if r in mapping]
        return f"[{', '.join(kept)}]" if kept else ""

    return _MARKER.sub(replace, result.answer)


def _how(how: str, removed: list[str]) -> str:
    """Report what the guardrail removed, so the trace shows whether it is too strict."""
    if not removed:
        return how
    shown = "; ".join(line[:70] for line in removed[:3])
    return f"{how}; guardrail removed {len(removed)} uncited line(s): {shown}"


def compose(question: str, plan: Plan, results: list[AgentResult]) -> tuple[str, list[Citation], bool, str]:
    """Returns (answer, citations, abstained, how)."""
    language = plan.language
    if len(results) == 1 and results[0].agent == "legal" and results[0].artifacts:
        # Draft text is an artifact, not a factual legal answer to strip or paraphrase.
        return results[0].answer, [], results[0].status != "ok", "structured legal artifact"
    if plan.out_of_scope:
        return NOT_SCOPE.get(language, NOT_SCOPE["en"]), [], True, "out of scope"
    if plan.clarification and not results:
        return plan.clarification, [], True, "clarification"

    citations: list[Citation] = []
    answers: list[tuple[AgentResult, str]] = []
    for result in results:
        mapping = {}
        for citation in result.citations:
            if citation.supported is False:
                continue
            mapping[citation.ref] = len(citations) + 1
            citations.append(citation.model_copy(update={"ref": mapping[citation.ref]}))
        answers.append((result, _renumber(result, mapping)))

    useful = [(r, text) for r, text in answers if r.status in {"ok", "needs_info"} and text.strip()]
    missing = list(dict.fromkeys(m for r in results for m in r.missing_info))
    unsupported = [c.text for r in results for c in r.claims if c.verdict == "unsupported"]
    partial = [c.text for r in results for c in r.claims if c.verdict == "partial"]
    if not useful:
        # An agent that explains why it cannot help ("contract review is not available",
        # "the fraud service is not running") is shown as written. The generic
        # "nothing found" line is for agents that searched the corpus and found nothing.
        notes = [text for r, text in answers if r.status in {"placeholder", "abstained", "error"} and not r.passages and text.strip()]
        searched = any(r.status in {"abstained", "error"} and r.passages for r in results)
        head = [NOTHING_FOUND.get(language, NOTHING_FOUND["en"])] if searched or not notes else []
        return "\n\n".join(head + notes), [], True, "nothing usable"

    # Tool agents (fraud scoring) return computed results, not passages. Their text is
    # shown as written: the LLM must not paraphrase a risk score, and the citation
    # guardrail would delete every line of it because a score has no [n] to cite.
    tools = [(r, text) for r, text in useful if not r.passages]
    tool_ids = {id(r) for r, _ in tools}
    answers = [(r, text) for r, text in answers if id(r) not in tool_ids]
    names = {agent_id: agent.card.name for agent_id, agent in AGENTS.items()}
    several = len(useful) > 1
    tool_text = "\n\n".join((f"**{names.get(r.agent, r.agent)}**\n" if several else "") + text for r, text in tools)
    if len(tools) == len(useful):
        text = tool_text + ("\n\n" + "\n".join(f"- {m}" for m in missing) if missing else "")
        # Their citations (the grants rules engine cites each programme's source page) are kept.
        return text, citations, False, "tool output, verbatim"

    def with_tools(text: str) -> str:
        return text + ("\n\n" + tool_text if tool_text else "")

    if len(answers) == 1 and not unsupported and not partial:
        text, removed = drop_uncited(answers[0][1])
        if several:
            text = f"**{names.get(answers[0][0].agent, answers[0][0].agent)}**\n{text}"
        if missing:
            text += "\n\n" + "\n".join(f"- {m}" for m in missing)
        return with_tools(text), citations, False, _how("single agent, passthrough" + (" + tool output" if tools else ""), removed)

    blocks = "\n\n".join(f"### {r.agent} ({r.status})\n{text}" for r, text in answers)
    prompt = get_prompt("orchestrator.composer")
    try:
        result = get_llm().chat(
            prompt.messages(
                language=language,
                question=question,
                agent_answers=blocks,
                unsupported=unsupported or "none",
                partial=partial or "none",
                missing_info=missing or "none",
            ),
            tier="compose",
            max_tokens=900,
        )
        text = result.text.strip()
        how = f"{prompt.ref} via {result.provider}/{result.model}"
    except LLMUnavailable:
        text = "\n\n".join(f"**{names.get(r.agent, r.agent)}**\n{t}" for r, t in answers)
        how = "concatenated (no LLM)"
    # The rewrite can lose markers the agents had; give them back before the guardrail.
    text, restored = restore_markers(text, [t for _, t in answers])
    if restored:
        how += f"; restored [n] on {restored} line(s) that restate cited agent lines"
    text, removed = drop_uncited(text)
    how = _how(how + (" + tool output" if tools else ""), removed)
    used = set()
    for group in _MARKER.findall(text):
        used.update(int(n) for n in re.split(r"\s*[,;]\s*", group))
    citations = [c for c in citations if c.ref in used] or citations
    return with_tools(text), citations, False, how
