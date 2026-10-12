"""The contract between the orchestrator and every agent.

An agent receives an AgentRequest (its sub-task from the planner, the
founder's original message, the shared profile, any uploaded documents) and
returns an AgentResult. Agents never call each other; the orchestrator
fans requests out, verifies what comes back and composes the reply.
Teammates implement `Agent.run` and register the agent in
app/agents/registry.py. Nothing else in the orchestrator changes.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import TraceStep
from app.schemas.rag import Passage

AgentStatus = Literal["ok", "abstained", "needs_info", "placeholder", "error"]


class FounderProfile(BaseModel):
    """What the system knows about the founder, shared by every agent.

    The planner and agents fill it in across turns, so a sector given to the
    business-plan agent is not asked again by the grants agent.
    """

    project_summary: str | None = None
    sector: str | None = None
    stage: Literal["idea", "creation", "early", "growth", "extension"] | None = None
    governorate: str | None = None
    legal_form: str | None = None
    founders_count: int | None = None
    employees: int | None = None
    funding_need_tnd: float | None = None
    has_startup_label: bool | None = None
    founder_age: int | None = None
    is_graduate: bool | None = None
    notes: list[str] = Field(default_factory=list)

    def known(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v not in (None, [], "")}

    def merge(self, updates: dict) -> tuple["FounderProfile", list[str]]:
        """Apply LLM-proposed updates field by field. Returns (profile, rejected fields).

        A value the schema refuses (e.g. stage="launching") is dropped, not raised:
        one bad field from the planner must not sink the turn.
        """
        profile, rejected = self, []
        for key, value in (updates or {}).items():
            if key not in FounderProfile.model_fields or value in (None, "", []):
                continue
            data = profile.model_dump()
            if key == "notes":
                value = list(dict.fromkeys(data["notes"] + (value if isinstance(value, list) else [str(value)])))
            data[key] = value
            try:
                profile = FounderProfile.model_validate(data)
            except ValueError:
                rejected.append(f"{key}={value!r}")
        return profile, rejected


class Attachment(BaseModel):
    filename: str
    mime: str
    text: str = ""
    pages: int | None = None
    extraction: str = Field(default="text", description="text, ocr, vision or none")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Citation(BaseModel):
    ref: int = Field(description="Number used in the answer text, e.g. [2]")
    doc_id: str
    title: str
    path: str
    page: int
    page_end: int | None = None
    act: str | None = None
    article: str | None = None
    publication_date: str | None = None
    publisher_url: str | None = None
    quote: str = Field(description="Start of the cited passage, shown as evidence")
    score: float | None = None
    score_meaning: str = "retrieval relevance, not legal correctness"
    supported: bool | None = Field(default=None, description="Verifier verdict on the claims citing it")


class Claim(BaseModel):
    text: str
    refs: list[int] = Field(default_factory=list)
    verdict: Literal["supported", "partial", "unsupported", "unchecked"] = "unchecked"


class AgentRequest(BaseModel):
    task: str = Field(description="Sub-task written by the planner for this agent")
    search_query: str | None = Field(default=None, description="Planner's French search query, for RAG agents")
    question: str
    language: str = "fr"
    profile: FounderProfile = Field(default_factory=FounderProfile)
    attachments: list[Attachment] = Field(default_factory=list)
    history: list[Turn] = Field(default_factory=list)


class AgentResult(BaseModel):
    agent: str
    status: AgentStatus
    answer: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list, description="Evidence the agent saw")
    missing_info: list[str] = Field(default_factory=list, description="Questions to ask the founder")
    profile_updates: dict = Field(default_factory=dict)
    confidence: float | None = None
    trace: list[TraceStep] = Field(default_factory=list)


class AgentCard(BaseModel):
    """What the planner reads to decide whether to call an agent."""

    id: str
    name: str
    description: str
    use_when: str
    owner: str
    status: Literal["ready", "placeholder"]
