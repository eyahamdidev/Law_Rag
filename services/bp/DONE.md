# Done (final gap-closing audit)

- Added optional evidence fields: `traction_note`, `ip_note`, `awards_note`, `permits_note` in questionnaire, PlanFacts, templates, parser_facts@v1, claim_guard, interview EXTRA.
- Financial regressions: implied customers (monthly vs annual vs unknown period), sources≠uses signal, chat/upload merge parity test.
- Live audit script: `scripts/live_audit.py` → `tmp/live_audit.txt` (Groq URL + prompt refs recorded; run reported `llm_available: false` — no DOCX generated live in this session).
- Mocked CI: **26 passed** — acceptance (10), plan_facts (2), writer_incomplete (1), financial_derive (8), evidence_fields (1), plan_doc_v14 (4).
