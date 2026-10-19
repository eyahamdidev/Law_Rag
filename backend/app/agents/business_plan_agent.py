"""Connector to the business-plan service (services/bp/, port 8104).

The service is the teammate's own application: it parses an uploaded plan,
checks its financials against Tunisian parameters and sector benchmarks,
scores each section, flags credibility problems and writes a DOCX review.
This agent sends it the founder's plan by reference (data/uploads/<sha256>,
the gateway's own convention) and shows its findings.

Without an uploaded plan the agent does not call the review: the service would
review the question text as if it were a plan (measured: "completeness 4/100").
It asks for the file, or points to the guided questionnaire page, which builds
a plan step by step through the service's /v1/chat interview.

The reply is written from the service's own answer, signals and artifacts, so
nothing it found is paraphrased.
"""

import base64
import time

from app.agents.base import Agent
from app.modules.bp import client
from app.modules.orchestrator import profile as session_profile
from app.schemas.agents import AgentCard, AgentRequest, AgentResult
from app.schemas.common import ModuleStatus, TraceStep

PLAN_EXTENSIONS = (".pdf", ".docx", ".xlsx", ".xls")
# The service names its hand-offs by its own module ids; founders see our agents' topics.
HANDOFF_NAMES = {
    "fr": {"aid": "le financement et les aides (BFPME, primes, programmes)", "law": "le droit des affaires"},
    "en": {"aid": "funding and support programmes (BFPME, premiums)", "law": "business law"},
    "ar": {"aid": "التمويل والمنح (BFPME، المنح، البرامج)", "law": "قانون الأعمال"},
}
MAX_SIGNALS = 6

TEXT = {
    "fr": {
        "ask": "Pour relire votre business plan, joignez-le (PDF, Word ou Excel). Pour en construire un pas à pas, utilisez l'onglet « Business plan » de l'application (questionnaire guidé).",
        "points": "Points à vérifier :",
        "report": "Rapport de relecture (Word) : {url}",
        "handoff": "Cette question relève plutôt de : {to}.",
        "down": "Le service business plan ne répond pas. Il se lance avec : uvicorn app.main:app --port 8104 (depuis services/bp).",
        "note": "Ces points signalent ce qui mérite une vérification ; ce n'est pas un avis d'investissement.",
    },
    "en": {
        "ask": "To review your business plan, attach it (PDF, Word or Excel). To build one step by step, use the app's \"Business plan\" tab (guided questionnaire).",
        "points": "Points to check:",
        "report": "Review report (Word): {url}",
        "handoff": "This question is better answered by: {to}.",
        "down": "The business-plan service is not responding. Start it with: uvicorn app.main:app --port 8104 (from services/bp).",
        "note": "These points flag what deserves a check; this is not investment advice.",
    },
    "ar": {
        "ask": "لمراجعة مخطط أعمالك، أرفقه (PDF أو Word أو Excel). لإعداده خطوة بخطوة، استعمل تبويب «مخطط الأعمال» في التطبيق (استبيان موجَّه).",
        "points": "نقاط للتثبت:",
        "report": "تقرير المراجعة (Word): {url}",
        "handoff": "هذا السؤال من اختصاص: {to}.",
        "down": "خدمة مخطط الأعمال لا تستجيب. تُشغَّل بالأمر: uvicorn app.main:app --port 8104 (من services/bp).",
        "note": "هذه النقاط تشير إلى ما يستحق التثبت، وليست رأيا استثماريا.",
    },
}

# Our FounderProfile field -> the service's profile key (see modules/orchestrator/profile.py).
PROFILE_KEYS = {
    "legal_form": "legal_form",
    "stage": "stage",
    "employees": "headcount",
    "funding_need_tnd": "funding_amount",
    "sector": "sector",
    "governorate": "governorate",
    "project_summary": "project_name",
}


def service_profile(request: AgentRequest) -> dict:
    known = request.profile.known()
    mapped = {theirs: known[ours] for ours, theirs in PROFILE_KEYS.items() if ours in known}
    return {**session_profile.get(request.session_id), **mapped}


def plan_file(request: AgentRequest):
    for attachment in request.attachments:
        if attachment.data_base64 and attachment.filename.lower().endswith(PLAN_EXTENSIONS):
            return attachment
    return None


def describe(response: dict, language: str) -> str:
    t = TEXT.get(language, TEXT["fr"])
    lines = [response.get("answer") or ""]
    signals = [s for s in response.get("signals") or [] if s.get("severity") in {"high", "review"}]
    if signals:
        lines.append(t["points"])
        lines += [f"- {s.get('message')}" for s in signals[:MAX_SIGNALS]]
    for artifact in response.get("artifacts") or []:
        if artifact.get("kind") == "docx":
            lines.append(t["report"].format(url=f"/api/files/{artifact['file_ref']}?kind=docx&name=business-plan-review"))
    handoff = response.get("handoff")
    if handoff:
        names = HANDOFF_NAMES.get(language, HANDOFF_NAMES["fr"])
        lines.append(t["handoff"].format(to=names.get(handoff.get("to"), handoff.get("to"))))
    lines.append(t["note"])
    return "\n".join(line for line in lines if line)


class BusinessPlanAgent(Agent):
    def __init__(self, card: AgentCard) -> None:
        self.card = card

    def run(self, request: AgentRequest) -> AgentResult:
        t = TEXT.get(request.language, TEXT["fr"])
        attachment = plan_file(request)
        if attachment is None:
            return AgentResult(agent=self.id, status="needs_info", answer=t["ask"], missing_info=[t["ask"]],
                               trace=[TraceStep(module="agent.business_plan", status=ModuleStatus.ok, detail="No plan attached; asked for one.")])
        ref = client.store_upload(base64.b64decode(attachment.data_base64))
        started = time.perf_counter()
        language = request.language if request.language in {"fr", "en", "ar"} else "fr"
        try:
            status_code, response = client.run(lang=language, file_ref=ref, profile=service_profile(request),
                                               options={"mode": "review"}, question=request.question)
        except client.BpUnavailable as error:
            return AgentResult(agent=self.id, status="error", answer=t["down"],
                               trace=[TraceStep(module="agent.business_plan.review", status=ModuleStatus.skipped, detail=str(error)[:200])])
        elapsed = (time.perf_counter() - started) * 1000
        models = sorted({s.get("model") for s in response.get("trace") or [] if s.get("model")})
        trace = [TraceStep(module="agent.business_plan.review", status=ModuleStatus.ok if status_code == 200 else ModuleStatus.skipped,
                           detail=(f"HTTP {status_code}, {attachment.filename}, {len(response.get('signals') or [])} signals, "
                                   f"models={models or 'rules only'} [{elapsed:.0f} ms]"))]
        if status_code != 200 or response.get("status") == "error":
            message = (response.get("error") or {}).get("message") or t["down"]
            return AgentResult(agent=self.id, status="error", answer=message, trace=trace)
        return AgentResult(agent=self.id, status="ok", answer=describe(response, request.language), trace=trace)
