"""Shared domain-worker placeholder.

A worker retrieves evidence inside its domain filter and drafts claims.
It may request one extra search when evidence is missing. The same local
model is reused across workers. OCR and search are tools; choosing them
is the agent step, and that step is not connected yet.
"""

from app.schemas.chat import WorkerDraft
from app.schemas.common import ModuleStatus


class DomainWorker:
    domain = "base"
    description = ""

    def draft(self, question: str) -> WorkerDraft:
        return WorkerDraft(
            domain=self.domain,
            status=ModuleStatus.placeholder,
            summary=(
                f"The {self.domain} worker is scaffolded. "
                "Retrieval and drafting are not connected yet."
            ),
            claims=[],
        )
