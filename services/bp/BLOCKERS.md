# Blockers / limitations

- **Live LLM quality not verified here:** `scripts/live_audit.py` ran but `LLMClient.available` was false (no key visible to the audit process). Config on disk points to Groq `llama-3.3-70b-versatile` / `llama-3.1-8b-instant` with `final_writer@v6` and `plan_writer@v2`; re-run audit locally with a valid `LLM_API_KEY` to inspect DOCX prose.
- `bfpme_extension.json` not updated with the four evidence questions (creation template only); extension uploads still use the same bank/schema via merge.
- Institutional six-section narrative still depends on optional live `final_writer`; deterministic path remains the CI contract.
