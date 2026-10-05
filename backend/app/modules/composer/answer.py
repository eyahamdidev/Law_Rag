"""Turn worker drafts into the text the web app shows.

Until retrieval returns passages, every cited-answer request abstains.
"""

from app.modules.domains.base import DomainWorker
from app.schemas.chat import WorkerDraft
from app.schemas.common import ModuleStatus, TraceStep


def compose(
    *,
    needs_clarification: bool,
    domains: list[str],
    drafts: list[WorkerDraft],
) -> tuple[str, bool, TraceStep]:
    if needs_clarification:
        answer = (
            "Which topic should be searched: company law, tax, banking, "
            "labour, or intellectual property? Nothing was retrieved."
        )
        return answer, True, TraceStep(
            module="composer",
            status=ModuleStatus.ok,
            detail="Asked for a domain because the router had no match.",
        )

    names = ", ".join(domains) if domains else "the selected domains"
    unused = ", ".join(draft.domain for draft in drafts) or names
    answer = (
        f"No passage was retrieved for {unused}, so there is no cited answer. "
        "Generation stays off until a passage is available. For a decision, "
        "read the official text or ask a qualified professional."
    )
    return answer, True, TraceStep(
        module="composer",
        status=ModuleStatus.ok,
        detail="Abstained because the retriever returned no passages.",
    )


def collect_drafts(workers: dict[str, DomainWorker], question: str, domains: list[str]) -> list[WorkerDraft]:
    drafts: list[WorkerDraft] = []
    for domain in domains:
        worker = workers.get(domain)
        if worker is not None:
            drafts.append(worker.draft(question))
    return drafts
