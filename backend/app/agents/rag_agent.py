"""Domain worker that answers from the corpus: retrieve, draft, cite.

One class serves every corpus-backed agent (legal, grants); they differ by
corpus filter and description. Steps:

1. Multi-query retrieval. The planner's French search query and the founder's
   own words are searched separately, fused with RRF, then reranked once
   against the founder's question. This is what makes an English or Arabic
   question find French gazette text.
2. Grounded draft (prompt rag.answer): JSON with claims tied to passage numbers.
3. At most one follow-up search when the draft abstains and proposes a query.
   That decision is the agentic step; the bound keeps latency predictable.

Without an LLM key the agent still returns the best passages as evidence and
says that no answer was generated.
"""

import time

from app.agents.base import Agent
from app.modules.rag.retrieval.hybrid import search_many
from app.prompts.library import get_prompt
from app.schemas.agents import AgentCard, AgentRequest, AgentResult, Citation, Claim
from app.schemas.common import ModuleStatus, TraceStep
from app.schemas.rag import Passage
from app.services.llm import LLMUnavailable, get_llm

# Groq's free tier allows 8,000 tokens per minute per model. 5 passages of
# 1,000 characters keep one draft near 1,800 tokens, so two agents and a
# follow-up search fit in the same minute (6 x 1,400 did not: 429 errors).
PASSAGES_PER_DRAFT = 5
PASSAGE_CHARS = 1000
LANGUAGE_NAMES = {"fr": "French", "ar": "Arabic", "en": "English"}


def format_passages(passages: list[Passage]) -> str:
    blocks = []
    for n, p in enumerate(passages, start=1):
        meta = [p.title]
        if p.act:
            meta.append(p.act)
        if p.article:
            meta.append(f"article {p.article}")
        meta.append(f"page {p.page_start}")
        if p.publication_date:
            # The JORT issue date, not the date the law was signed (Loi 2018-20: signed 17 April, JORT 20 April).
            meta.append(f"JORT publication date {p.publication_date}")
        blocks.append(f"[{n}] {' | '.join(meta)}\n{p.text[:PASSAGE_CHARS]}")
    return "\n\n".join(blocks)


def citation_from(n: int, p: Passage) -> Citation:
    return Citation(
        ref=n,
        doc_id=p.doc_id,
        title=p.title,
        path=p.path,
        page=p.page_start,
        page_end=p.page_end,
        act=p.act,
        article=p.article,
        publication_date=p.publication_date,
        publisher_url=p.publisher_url,
        quote=p.text[:320],
        score=p.score,
    )


def profile_text(request: AgentRequest) -> str:
    known = request.profile.known()
    return ", ".join(f"{k}={v}" for k, v in known.items()) or "nothing known yet"


class RagAgent(Agent):
    def __init__(self, card: AgentCard, corpora: list[str], domain_label: str) -> None:
        self.card = card
        self.corpora = corpora
        self.domain_label = domain_label

    def _draft(self, request: AgentRequest, passages: list[Passage]) -> tuple[dict, str, float]:
        prompt = get_prompt("rag.answer")
        data, result = get_llm().chat_json(
            prompt.messages(
                domain=self.domain_label,
                language=request.language,
                language_name=LANGUAGE_NAMES.get(request.language, "French"),
                task=request.task,
                question=request.question,
                profile=profile_text(request),
                passages=format_passages(passages),
            ),
            tier="main",
        )
        return data, f"{prompt.ref} via {result.provider}/{result.model}", result.latency_ms

    def run(self, request: AgentRequest) -> AgentResult:
        trace: list[TraceStep] = []
        started = time.perf_counter()
        queries = [request.search_query or "", request.question]
        passages = search_many(queries, rerank_query=request.question, corpora=self.corpora, k=PASSAGES_PER_DRAFT)
        trace.append(
            TraceStep(
                module=f"agent.{self.id}.retrieve",
                status=ModuleStatus.ok,
                detail=(
                    f"{len(passages)} passages for {len([q for q in queries if q])} queries "
                    f"in {', '.join(self.corpora)} ({(time.perf_counter() - started) * 1000:.0f} ms)."
                ),
            )
        )
        if not passages:
            return AgentResult(
                agent=self.id,
                status="abstained",
                answer="No passage in the corpus matches this question.",
                trace=trace,
            )

        try:
            data, ref, latency = self._draft(request, passages)
        except LLMUnavailable as error:
            trace.append(TraceStep(module=f"agent.{self.id}.draft", status=ModuleStatus.skipped, detail=str(error)[:200]))
            top = passages[:3]
            listing = "; ".join(f"[{n}] {p.citation_label()}" for n, p in enumerate(top, start=1))
            reason = (
                "no language model is configured"
                if not get_llm().available
                else "the language models are busy or rate-limited right now; try again in a minute"
            )
            return AgentResult(
                agent=self.id,
                status="ok",
                answer=f"No answer was generated ({reason}). Most relevant passages: {listing}.",
                citations=[citation_from(n, p) for n, p in enumerate(top, start=1)],
                passages=top,
                trace=trace,
            )
        trace.append(TraceStep(module=f"agent.{self.id}.draft", status=ModuleStatus.ok, detail=f"{ref}, {latency:.0f} ms."))

        follow_up = (data.get("follow_up_query") or "").strip()
        if data.get("abstain") and follow_up:
            extra = search_many([follow_up], rerank_query=request.question, corpora=self.corpora, k=PASSAGES_PER_DRAFT)
            known = {p.chunk_id for p in passages}
            added = [p for p in extra if p.chunk_id not in known][: max(0, 7 - len(passages))]
            trace.append(
                TraceStep(
                    module=f"agent.{self.id}.research",
                    status=ModuleStatus.ok,
                    detail=f"Follow-up search '{follow_up[:80]}' added {len(added)} passages.",
                )
            )
            if added:
                passages = passages + added
                try:
                    data, ref, latency = self._draft(request, passages)
                    trace.append(TraceStep(module=f"agent.{self.id}.draft", status=ModuleStatus.ok, detail=f"retry {ref}, {latency:.0f} ms."))
                except LLMUnavailable as error:
                    trace.append(TraceStep(module=f"agent.{self.id}.draft", status=ModuleStatus.skipped, detail=str(error)[:200]))

        claims = []
        for item in data.get("claims") or []:
            if isinstance(item, dict) and item.get("text"):
                refs = [int(r) for r in item.get("refs") or [] if str(r).isdigit()]
                claims.append(Claim(text=str(item["text"]), refs=refs))
        used = sorted({r for c in claims for r in c.refs if 1 <= r <= len(passages)})
        abstained = bool(data.get("abstain"))
        missing = [str(m) for m in data.get("missing_info") or [] if m]
        return AgentResult(
            agent=self.id,
            status="abstained" if abstained else ("needs_info" if missing and not claims else "ok"),
            answer=str(data.get("answer") or ""),
            claims=claims,
            citations=[citation_from(n, passages[n - 1]) for n in used],
            passages=passages,
            missing_info=missing,
            trace=trace,
        )
