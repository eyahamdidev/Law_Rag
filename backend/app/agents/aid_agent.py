"""Aid and grants specialist agent for Tunisian founders.

Two paths:
- eligibility ("which programme fits me", or a message stating founder facts):
  the profile is extracted, the deterministic rules engine matches it against
  the catalogue, and the answer is written from the match itself, so no
  eligibility, amount or threshold comes from an LLM. Figures the catalogue
  marks as unverified are shown as "to confirm", never applied.
- general grants questions ("what does SOTUGAR guarantee?"): the RAG agent
  over the grants corpus, whose claims go through the verifier.

Citations point to the indexed page each programme's catalogue entry cites.
"""

from app.agents.base import Agent
from app.agents.rag_agent import RagAgent
from app.modules.aid.extractor import extract_profile, heuristic_extract_profile
from app.modules.aid.matcher import match
from app.modules.aid.rules_engine import _normalize, detect_law_handoff
from app.modules.aid.sources import source_chunk
from app.schemas.agents import AgentCard, AgentRequest, AgentResult, Citation
from app.schemas.aid import AidMatchResponse, AidProfile
from app.schemas.common import ModuleStatus, TraceStep

MAX_EXCLUDED = 3

# Words that ask for a match against the founder's own profile.
ELIGIBILITY_CUES = (
    "eligible", "eligibilite", "me convient", "correspond", "quel programme", "quelles aides",
    "quel financement", "which programme", "which program", "which grant", "fits me", "qualify",
    "يناسب", "مؤهل", "اي برنامج", "ما هي المنح",
)

TEXT = {
    "fr": {
        "head": "Programmes qui correspondent à votre profil (moteur de règles ; {criteria}) :",
        "none": "Aucun programme du catalogue ne correspond à ces critères ({criteria}).",
        "confirm": "À confirmer auprès de l'organisme (montant ou seuil non sourcé) : {items}",
        "zones": "Zones éligibles par délégation : {where}.",
        "docs": "Documents (liste indicative) : {docs}",
        "excluded": "Non retenus :",
        "note": "L'éligibilité finale est décidée par l'organisme ; vérifiez sur son formulaire officiel.",
        "any": "non précisé",
    },
    "en": {
        "head": "Programmes matching your profile (rules engine; {criteria}):",
        "none": "No catalogue programme matches these criteria ({criteria}).",
        "confirm": "To confirm with the provider (amount or threshold not sourced): {items}",
        "zones": "Eligible zones are delegations: {where}.",
        "docs": "Documents (indicative list): {docs}",
        "excluded": "Not retained:",
        "note": "The provider makes the final eligibility decision; check its official form.",
        "any": "not given",
    },
    "ar": {
        "head": "البرامج التي تتوافق مع ملفك (محرك القواعد؛ {criteria}):",
        "none": "لا يتوافق أي برنامج في الكتالوج مع هذه المعايير ({criteria}).",
        "confirm": "يجب التثبت لدى الجهة المانحة (مبلغ أو سقف غير موثق): {items}",
        "zones": "المناطق المؤهلة تحدد حسب المعتمدية: {where}.",
        "docs": "الوثائق (قائمة تقريبية): {docs}",
        "excluded": "برامج غير مختارة:",
        "note": "القرار النهائي بشأن الأهلية للجهة المانحة؛ تثبت من استمارتها الرسمية.",
        "any": "غير محدد",
    },
}


def states_facts(profile: AidProfile) -> bool:
    """True when the profile says something about the founder, not only the instrument wanted."""
    return any([
        profile.stage != "unspecified", profile.sector, profile.funding_need_tnd, profile.employees,
        profile.governorate, profile.is_graduate, profile.has_startup_label,
    ])


def asks_eligibility(question: str) -> bool:
    text = _normalize(question)
    return any(_normalize(cue) in text for cue in ELIGIBILITY_CUES)


def program_citations(response: AidMatchResponse) -> list[Citation]:
    citations = []
    for ref, program in enumerate(response.programs, 1):
        chunk = source_chunk(program.source_file, program.source_page)
        citations.append(Citation(
            ref=ref,
            doc_id=chunk["doc_id"] if chunk else f"catalog:{program.id}",
            title=chunk["title"] if chunk else program.name,
            path=program.source_file or "grants_and_financial_aids",
            page=program.source_page or 1,
            quote=chunk["text"][:180] if chunk else "",
            score_meaning="source of the catalogue entry (rules engine match)",
            source_kind=chunk.get("source_kind", "unknown") if chunk else "unknown",
        ))
    return citations


def describe(profile: AidProfile, response: AidMatchResponse, language: str) -> str:
    t = TEXT.get(language, TEXT["fr"])
    criteria = ", ".join(
        f"{name}={value}" for name, value in [
            ("stage", profile.stage if profile.stage != "unspecified" else t["any"]),
            ("sector", profile.sector or t["any"]),
            ("need", profile.need if profile.need != "unspecified" else t["any"]),
            ("TND", f"{profile.funding_need_tnd:,.0f}" if profile.funding_need_tnd else None),
            ("governorate", profile.governorate),
        ] if value
    )
    if not response.programs:
        lines = [t["none"].format(criteria=criteria)]
    else:
        lines = [t["head"].format(criteria=criteria)]
        for ref, program in enumerate(response.programs, 1):
            lines.append(f"{ref}. **{program.name}** ({program.provider}) : {program.summary} [{ref}]")
            to_confirm = {k: v for k, v in program.unverified.items() if k != "reason"}
            if to_confirm:
                lines.append("   - " + t["confirm"].format(items=", ".join(f"{k}={v:,}" for k, v in to_confirm.items())))
            if program.conditions.get("zones_by_delegation"):
                lines.append("   - " + t["zones"].format(where=f"{program.source_file.rsplit('/', 1)[-1]}, {program.conditions['zones_by_delegation']}"))
            if program.required_documents:
                lines.append("   - " + t["docs"].format(docs="; ".join(program.required_documents[:5])))
    if response.excluded_programs:
        lines.append(t["excluded"])
        lines += [f"- {e['name']}: {'; '.join(e.get('reasons', []))}" for e in response.excluded_programs[:MAX_EXCLUDED]]
    lines.append(t["note"])
    return "\n".join(lines)


class AidAgent(Agent):
    """Specialist agent for Tunisian grants, loans, and aid programs."""

    def __init__(self, card: AgentCard) -> None:
        self.card = card
        self.fallback = RagAgent(card, corpora=["grants"], domain_label="funding and support programmes")

    def run(self, request: AgentRequest) -> AgentResult:
        trace: list[TraceStep] = []

        # 1. Statute questions belong to the legal agent
        handoff = detect_law_handoff(request.question)
        if handoff:
            trace.append(TraceStep(
                module="agent.grants.handoff",
                status=ModuleStatus.ok,
                detail=f"Statute inquiry detected in aid agent; delegating legal explanation to {handoff.to}.",
            ))
            return AgentResult(
                agent=self.id,
                status="ok",
                answer=(
                    f"Votre question concerne le texte juridique officiel ({handoff.question}). "
                    "Cette analyse relève du spécialiste juridique (Law / P1)."
                ),
                trace=trace,
            )

        # 2. General grants question -> cited RAG answer
        known = request.profile
        session_facts = any([known.stage, known.sector, known.funding_need_tnd, known.governorate])
        if not states_facts(heuristic_extract_profile(request.question)) and not (session_facts and asks_eligibility(request.question)):
            result = self.fallback.run(request)
            result.trace.insert(0, TraceStep(
                module="agent.grants.route", status=ModuleStatus.ok,
                detail="No founder facts and no eligibility request: answered from the grants corpus (RAG).",
            ))
            return result

        # 3. Eligibility: extract and merge profile facts
        existing_profile = AidProfile(
            stage={"early": "creation"}.get(known.stage, known.stage) or "unspecified",  # AidProfile has no "early"
            sector=known.sector or "",
            funding_need_tnd=known.funding_need_tnd,
            governorate=known.governorate,
            is_innovative=known.has_startup_label or None,
            has_startup_label=known.has_startup_label or None,
            is_graduate=known.is_graduate or None,
            free_text=request.question,
        )
        extracted_profile, missing_fields, extractor_ref = extract_profile(request.question, known_profile=existing_profile)
        trace.append(TraceStep(
            module="agent.grants.intake",
            status=ModuleStatus.ok,
            detail=f"Profile extracted via {extractor_ref} (missing: {missing_fields or 'none'}).",
        ))

        # 4. Deterministic rule matching
        match_resp = match(extracted_profile)
        trace.extend(match_resp.trace)

        # 5. Answer written from the match (no LLM: eligibility and figures are shown as computed)
        language = request.language if request.language in TEXT else "fr"
        citations = program_citations(match_resp)
        trace.append(TraceStep(
            module="agent.grants.explanation",
            status=ModuleStatus.ok,
            detail=(f"Deterministic answer: {len(match_resp.programs)} matched, {len(match_resp.excluded_programs)} excluded, "
                    f"{sum(1 for c in citations if not c.doc_id.startswith('catalog:'))}/{len(citations)} sources found in the index."),
        ))

        profile_updates = {}
        if extracted_profile.sector:
            profile_updates["sector"] = extracted_profile.sector
        if extracted_profile.stage != "unspecified":
            profile_updates["stage"] = extracted_profile.stage
        if extracted_profile.funding_need_tnd:
            profile_updates["funding_need_tnd"] = extracted_profile.funding_need_tnd

        return AgentResult(
            agent=self.id,
            status="ok" if match_resp.programs or not missing_fields else "needs_info",
            answer=describe(extracted_profile, match_resp, language),
            citations=citations,
            missing_info=missing_fields if not match_resp.programs else [],
            profile_updates=profile_updates,
            confidence=1.0 if match_resp.programs else 0.5,
            trace=trace,
        )
