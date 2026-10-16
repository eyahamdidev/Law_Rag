# Legal guidance — Meher's work area

`agent.py` is registered as `legal`. `engine.py` provides legal-only retrieval,
quote checks, evidence review and conservative fallback. Structured drafting
requests delegate to the cooperating `contract_drafting` module.

Guidance supports local or hosted LLMs, multilingual retrieval, source/version
flags, local OCR, procedural checklists and missing-information questions.
Supplied law editions are not certified current. Corrective retrieval is one
additional local search, followed by official research links if insufficient.

Founder facts arrive through `AgentRequest.profile`; uploaded documents arrive
through `AgentRequest.attachments`. This is an integration interface, not a
completed login or user-account system.

See `docs/LEGAL_WORKSPACE.md` from the repository root for both legal features.
