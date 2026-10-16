"""Generate grounded natural-language explanations from deterministic aid match results.

The LLM drafts the explanation citing the official checklists and source pages.
The LLM never overrides or decides eligibility.
"""

from app.prompts.library import get_prompt
from app.schemas.agents import Citation, Claim
from app.schemas.aid import AidMatchResponse
from app.services.llm import LLMUnavailable, get_llm
from app.modules.rag.retrieval.hybrid import search


def explain_match(
    question: str,
    match_response: AidMatchResponse,
    language: str = "fr",
) -> tuple[str, list[Citation], list[Claim], str]:
    """Draft grounded explanation of matching programs and checklists."""
    citations: list[Citation] = []
    claims: list[Claim] = []
    evidence_blocks: list[str] = []

    # Use indexed aid passages when available; deterministic catalog evidence
    # remains the fallback when ingestion has not been run.
    try:
        passages = search(question, corpora=["grants"], k=5)
    except (OSError, RuntimeError, ValueError):
        passages = []

    # Build evidence passages from eligible programs
    ref_idx = 1
    for program in match_response.programs:
        doc_list = ", ".join(program.required_documents[:4]) if program.required_documents else "Formulaire officiel"
        quote_text = f"{program.name} ({program.provider}): {program.summary} Documents: {doc_list}."
        
        cit = Citation(
            ref=ref_idx,
            doc_id=f"grants:{program.id}",
            title=program.name,
            path=program.source_file or "grants_and_financial_aids",
            page=program.source_page or 1,
            quote=quote_text[:180],
            score=1.0,
            score_meaning="rule engine match",
            supported=True,
        )
        citations.append(cit)
        evidence_blocks.append(f"[{ref_idx}] {program.name} ({program.provider}): {quote_text}")
        claims.append(
            Claim(
                text=f"{program.name} est éligible pour votre profil ({program.summary})",
                refs=[ref_idx],
                verdict="supported",
            )
        )
        ref_idx += 1

    for passage in passages:
        citations.append(
            Citation(
                ref=ref_idx,
                doc_id=passage.doc_id,
                title=passage.title,
                path=passage.path,
                page=passage.page_start,
                page_end=passage.page_end,
                act=passage.act,
                article=passage.article,
                quote=passage.text[:180],
                score=passage.score,
                score_meaning=passage.score_kind,
                supported=None,
            )
        )
        evidence_blocks.append(f"[{ref_idx}] {passage.citation_label()}: {passage.text[:700]}")
        ref_idx += 1

    # Format deterministic rule trace for prompt
    eval_traces = []
    for exc in match_response.excluded_programs[:3]:
        reasons_str = "; ".join(exc.get("reasons", ["Critères non remplis"]))
        eval_traces.append(f"- Exclu {exc.get('name')}: {reasons_str}")

    passages_text = "\n".join(evidence_blocks) if evidence_blocks else "Aucun programme éligible identifié pour ces critères stricts."
    claims_text = "\n".join(eval_traces) if eval_traces else "Tous les programmes analysés respectent les critères."

    # If offline or no eligible programs, provide deterministic template
    llm = get_llm()
    prompt_spec = get_prompt("aid.explain_match", "v2")
    version_ref = prompt_spec.ref

    if not llm.available or not match_response.programs:
        if match_response.programs:
            lines = ["### Programmes éligibles identifiés\n"]
            for i, p in enumerate(match_response.programs, 1):
                lines.append(f"**[{i}] {p.name}** ({p.provider})")
                lines.append(f"- *Objet:* {p.summary}")
                if p.required_documents:
                    docs = "\n  - ".join(p.required_documents[:5])
                    lines.append(f"- *Documents requis:*\n  - {docs}")
                if p.official_form_link:
                    lines.append(f"- *Formulaire officiel:* `{p.official_form_link}`\n")
            if match_response.excluded_programs:
                lines.append("### Programmes non retenus")
                for exc in match_response.excluded_programs[:3]:
                    lines.append(f"- **{exc['name']}**: {'; '.join(exc.get('reasons', []))}")
            answer = "\n".join(lines)
        else:
            answer = (
                "Aucun programme de financement ou subvention ne correspond exactement aux critères saisis. "
                + (f"Motifs d'exclusion: {'; '.join(eval_traces)}" if eval_traces else "")
            )
        return answer, citations, claims, "deterministic@v1"

    messages = prompt_spec.messages(
        task="Expliquer les programmes éligibles et lister les pièces à fournir",
        question=question,
        passages=passages_text,
        claims=claims_text,
        language=language,
    )

    try:
        result = llm.chat(messages, tier="main", max_tokens=400)
        return result.text, citations, claims, version_ref
    except LLMUnavailable:
        # Fallback to deterministic summary
        lines = ["### Programmes éligibles\n"]
        for i, p in enumerate(match_response.programs, 1):
            lines.append(f"**[{i}] {p.name}** ({p.provider}): {p.summary}")
        return "\n".join(lines), citations, claims, "deterministic@fallback"
