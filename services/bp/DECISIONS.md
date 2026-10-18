# Decisions (simplest option taken, one line each)

- PlanFacts pydantic added as a validation/view layer over context.values; runtime merge stays in profile.Context (no duplicate store).
- Provenance labels in reports: questionnaire/orchestrator -> "form", document -> "upload", derived -> "calculation".
- Executive summary: deterministic synthesis after all sections; LLM polish optional on that block only if configured.
- Critic advisor context includes flat upload text for market/finance/exec sections so quotes match upload-only plans.
- The chat IS the one form: app/questionnaire.py BANK drives /v1/questionnaire and /v1/chat; "Add more detail" kept as the revisit path for skippable questions (deleting it would remove the only way back to skipped items).
- Field list from the prompt mapped to existing bank ids (revenue->revenue_by_year, ask->funding_need_amount, price->pricing, ...): no renames.
- Governorate: exact/folded match against the 24-list only; typos are re-asked (prompt: "never guess Tunis").
- Implied customers computed only when pricing parses as a single number, assumed monthly, stated as an assumption line.
- currency: extracted from doc text (EUR/MAD/USD must beat TND by count) or the new optional bank Q 'currency'; default TND; never converted, only relabelled (plan_doc, writer, chart, claim_guard).
- extraction: regex/table facts keep priority; one llm_facts call (parser_facts@v1, full text, temp 0) fills only the gaps; facts dumped to tmp/facts_<name>.json.
