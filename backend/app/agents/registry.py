"""Agents the planner can route to.

To plug in your agent: subclass app.agents.base.Agent, implement
run(AgentRequest) -> AgentResult, and replace the PlaceholderAgent entry
below with your class. Keep the card's id; the routing evaluation and the
planner prompt refer to it. Describe in `use_when` the messages your agent
should get: the planner reads only the cards.
"""

from app.agents.base import Agent, PlaceholderAgent
from app.agents.rag_agent import RagAgent
from app.schemas.agents import AgentCard

LEGAL = AgentCard(
    id="legal",
    name="Legal",
    description=(
        "Tunisian business law from the official texts: company forms and creation "
        "(Code des sociétés commerciales: SARL, SUARL, SA), the Startup Act label, its "
        "benefits and the BCT startup circulars, the investment law and its decrees, "
        "banking law, foreign-exchange rules, crowdfunding law, insolvency procedures."
    ),
    use_when="The founder asks what the law requires, allows or grants, or which legal form or procedure applies.",
    owner="law team",
    status="ready",
)
GRANTS = AgentCard(
    id="grants",
    name="Grants and financing",
    description=(
        "Funding and support programmes for Tunisian founders: BFPME loans and checklists, "
        "BTS and FONAPRAM credits, SOTUGAR guarantees, investment premiums (decree 2017-389, "
        "regional development zones), Startup Tunisia programmes, donors, accelerators and calls."
    ),
    use_when="The founder asks how to finance the project, which grant, loan, premium or programme fits, or which documents a funder requires.",
    owner="orchestrator owner",
    status="ready",
)
BUSINESS_PLAN = AgentCard(
    id="business_plan",
    name="Business plan and BMC",
    description="Business Model Canvas, lean canvas, business plan structure, financial projections, Tunisian accounting standards, sector benchmarks.",
    use_when="The founder wants to build or review a business model, canvas, plan or financial forecast.",
    owner="business-plan teammate",
    status="placeholder",
)
MARKETING = AgentCard(
    id="marketing",
    name="Marketing strategy",
    description="Target market, positioning, go-to-market, pricing and digital marketing for a Tunisian startup.",
    use_when="The founder asks how to find customers, position, price or promote the product.",
    owner="marketing teammate",
    status="placeholder",
)
FRAUD = AgentCard(
    id="fraud",
    name="Contract and fraud review",
    description="Reviews an uploaded contract, invoice or statement for unfair terms and fraud signals.",
    use_when=(
        "The founder asks whether a contract, invoice, offer or agreement is suspicious, fair or safe "
        "to sign, with or without the file attached (the agent asks for it if needed)."
    ),
    owner="fraud teammate",
    status="placeholder",
)

AGENTS: dict[str, Agent] = {
    "legal": RagAgent(LEGAL, corpora=["law"], domain_label="Tunisian business law"),
    "grants": RagAgent(GRANTS, corpora=["grants"], domain_label="funding and support programmes"),
    "business_plan": PlaceholderAgent(BUSINESS_PLAN),
    "marketing": PlaceholderAgent(MARKETING),
    "fraud": PlaceholderAgent(FRAUD),
}


def cards() -> list[AgentCard]:
    return [agent.card for agent in AGENTS.values()]


def cards_for_prompt() -> str:
    return "\n".join(
        f"- {c.id}: {c.description} Use when: {c.use_when}"
        + (" (not connected yet; still route to it when it fits)" if c.status == "placeholder" else "")
        for c in cards()
    )
