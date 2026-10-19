# Demonstrating the legal component

Open the repository's `Legal-Agent.code-workspace` in VS Code. Run `run-agent.cmd`, then open `http://127.0.0.1:8000/legal.html`.

## Guidance

Choose the response language and ask a focused question, for example:

- English: What conditions must an invention meet to be patentable?
- French: Quels signes peuvent constituer une marque de fabrique ?
- Arabic: ما هي شروط حماية الاختراع ببراءة؟
- Startup label: Quelles sont les conditions et démarches du label startup en Tunisie ?
- Software: Quels droits d'auteur protègent un logiciel ?

Read the cited quote and open the linked source. Distinguish legislation, explanatory guides and OCR text. Sources reflect supplied editions; a publication date is not necessarily an effective date. For a procedural view, use the sourced checklist selector. Unsupported answers must not be replaced with guessed rules.

## Contract drafting

1. Fill the founder profile if available. The dedicated form does not create a login account.
2. Choose an agreement: NDA, founders, shareholders, investment, grant/donor, services, partnership, consortium, IP licence or IP assignment.
3. Reuse profile details using the explicit buttons, then confirm each party's legal identity, address and role.
4. Supply the actual proposed governing law, effective date, purpose and agreed terms. Founders/shareholders require a complete ownership allocation totalling 100 percent.
5. Optionally upload PDF/DOCX/TXT facts. For a long PDF select the relevant range of at most 40 pages. Review extracted text, truncation notices and unreadable-page warnings. No source text is automatically inserted as an agreed term.
6. Ask for document-based suggestions and confirm the attributed values you want to use. Missing or unsupported values remain for intake.
7. Generate the unsigned preview. Optional AI refines wording; failed checks retain the filled drafting structure.
8. Download the editable Word draft and review it before any real-world use. The preview's export does not sign, file or accept the agreement.

The orchestrator owner can use the same workflow through `legal_contract` in `/api/chat`; the structured artifact must be displayed without paraphrasing its clauses. See `LEGAL_WORKSPACE.md` for the exact integration contract.
