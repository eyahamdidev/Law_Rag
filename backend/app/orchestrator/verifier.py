"""Verify agent output before it reaches the founder.

1. Citation validity, in code. Every [n] in an answer and every claim ref
   must point at a passage the agent was actually given, and that passage
   must exist in the index with the same document and page. A model is not
   the source of this check.
2. Claim support, by the LLM (prompt verifier.claims). Each claim is judged
   only against the passages it cites. A claim with no valid ref is
   unsupported without a model call.

The composer removes unsupported claims and flags partial ones.
"""

import re
from dataclasses import dataclass, field

from app.config import settings
from app.modules.rag.ingestion.pipeline import load_chunks
from app.prompts.library import get_prompt
from app.schemas.agents import AgentResult
from app.services.llm import LLMUnavailable, get_llm

_MARKER = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
_index_cache: dict[str, set[tuple[str, int]]] = {}


def _index(strategy: str) -> set[tuple[str, int]]:
    if strategy not in _index_cache:
        pages = set()
        for row in load_chunks(strategy):
            for page in range(row["page_start"], row["page_end"] + 1):
                pages.add((row["doc_id"], page))
        _index_cache[strategy] = pages
    return _index_cache[strategy]


def markers(text: str) -> list[int]:
    return [int(n) for group in _MARKER.findall(text) for n in re.split(r"\s*[,;]\s*", group)]


@dataclass
class Verification:
    citations_checked: int = 0
    citations_valid: int = 0
    claims_total: int = 0
    supported: int = 0
    partial: int = 0
    unsupported: int = 0
    claim_check: str = "not run"
    notes: list[str] = field(default_factory=list)

    @property
    def citation_validity(self) -> float | None:
        return self.citations_valid / self.citations_checked if self.citations_checked else None

    def as_dict(self) -> dict:
        return {
            "citation_validity": self.citation_validity,
            "citations_checked": self.citations_checked,
            "claims_total": self.claims_total,
            "supported": self.supported,
            "partial": self.partial,
            "unsupported": self.unsupported,
            "claim_check": self.claim_check,
            "notes": self.notes,
        }


def _check_citations(result: AgentResult, report: Verification) -> None:
    index = _index(settings.chunk_strategy)
    n_passages = len(result.passages)
    for ref in markers(result.answer) + [r for c in result.claims for r in c.refs]:
        report.citations_checked += 1
        if 1 <= ref <= n_passages:
            passage = result.passages[ref - 1]
            if (passage.doc_id, passage.page_start) in index:
                report.citations_valid += 1
                continue
        report.notes.append(f"{result.agent}: citation [{ref}] does not match a passage it was given")
    for claim in result.claims:
        claim.refs = [r for r in claim.refs if 1 <= r <= n_passages]


def _check_claims(results: list[AgentResult], report: Verification) -> None:
    items, lines = [], []
    for result in results:
        for claim in result.claims:
            report.claims_total += 1
            if not claim.refs:
                claim.verdict = "unsupported"
                continue
            evidence = "\n".join(f"  [{r}] {result.passages[r - 1].text[:900]}" for r in claim.refs)
            lines.append(f"Claim {len(items)}: {claim.text}\nCited passages:\n{evidence}")
            items.append(claim)
    if not items:
        report.claim_check = "no claims with citations"
    else:
        prompt = get_prompt("verifier.claims")
        try:
            data, result = get_llm().chat_json(prompt.messages(claims="\n\n".join(lines)), tier="fast", max_tokens=900)
            for verdict in data.get("verdicts") or []:
                index = verdict.get("claim")
                if isinstance(index, int) and 0 <= index < len(items) and verdict.get("verdict") in {"supported", "partial", "unsupported"}:
                    items[index].verdict = verdict["verdict"]
            report.claim_check = f"{prompt.ref} via {result.provider}/{result.model}"
        except (LLMUnavailable, ValueError) as error:
            report.claim_check = f"skipped: {str(error)[:120]}"
    for result in results:
        for claim in result.claims:
            if claim.verdict == "supported":
                report.supported += 1
            elif claim.verdict == "partial":
                report.partial += 1
            elif claim.verdict == "unsupported":
                report.unsupported += 1
        verdict_by_ref: dict[int, bool] = {}
        for claim in result.claims:
            for ref in claim.refs:
                ok = claim.verdict in {"supported", "partial"}
                verdict_by_ref[ref] = verdict_by_ref.get(ref, False) or ok
        for citation in result.citations:
            if citation.ref in verdict_by_ref:
                citation.supported = verdict_by_ref[citation.ref]


def verify(results: list[AgentResult]) -> Verification:
    report = Verification()
    checked = [r for r in results if r.status in {"ok", "needs_info"} and r.passages]
    for result in checked:
        _check_citations(result, report)
    _check_claims(checked, report)
    return report
