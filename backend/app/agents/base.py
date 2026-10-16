"""Base class every agent implements. See app/schemas/agents.py for the contract."""

from app.schemas.agents import AgentCard, AgentRequest, AgentResult
from app.schemas.common import ModuleStatus, TraceStep


class Agent:
    card: AgentCard

    @property
    def id(self) -> str:
        return self.card.id

    def run(self, request: AgentRequest) -> AgentResult:
        raise NotImplementedError


class PlaceholderAgent(Agent):
    """Registered so the planner can route to it; replaced by the owner's agent."""

    def __init__(self, card: AgentCard) -> None:
        self.card = card

    def run(self, request: AgentRequest) -> AgentResult:
        return AgentResult(
            agent=self.id,
            status="placeholder",
            answer=(
                f"The {self.card.name} agent is not connected yet "
                f"({self.card.owner} is building it). This part of the question is not answered."
            ),
            trace=[
                TraceStep(
                    module=f"agent.{self.id}",
                    status=ModuleStatus.placeholder,
                    detail=f"Task received: {request.task[:160]}",
                )
            ],
        )
