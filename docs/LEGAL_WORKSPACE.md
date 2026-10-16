# Legal feature handoff

| Feature | Entry point |
|---|---|
| Guidance and evidence checks | `backend/app/agents/legal_guidance/engine.py` |
| Adapter, agent ID `legal` | `backend/app/agents/legal_guidance/agent.py` |
| Ten drafting structures | `backend/app/agents/contract_drafting/catalog.py` |
| Drafting and Word export | `backend/app/agents/contract_drafting/service.py` |
| Schemas and routes | `backend/app/schemas/legal.py`, `backend/app/api/routes/legal.py` |
| UI | `frontend/legal.html`, `legal.js`, `legal.css` |

Legal retrieval filters to `law`; funding and fraud remain separate shared features.

## Endpoints

- `GET /api/legal/status`: corpus and configured capabilities.
- `GET /api/legal/contracts/types?language=fr`: catalogue and required fields.
- `POST /api/legal/guidance`: question, language (`fr/ar/en`), jurisdiction, profile and optional extracted attachments. Returns mode, result, citations, limitations and research links.
- `POST /api/legal/checklists`: task (`startup_label/company_creation/patent/trademark/copyright`), language, jurisdiction and profile. Only supported claims become steps; otherwise evidence excerpts appear.
- `POST /api/legal/documents/extract`: multipart file, optional `local_ocr`, PDF `page_start` and `page_end`. PDF/DOCX/TXT, 10 MiB; a PDF may contain up to 600 pages, with at most 40 read per request and four OCR pages. This supports selecting relevant parts of long consortium agreements. Text capped at 12,000 characters with warning. Original page numbers are retained. Files are not saved.
- `POST /api/legal/contracts/suggest`: DraftRequest with attachments; literal attributed suggestions require confirmation.
- `POST /api/legal/contracts/draft`: returns `needs_info` or `draft_for_review`. `export_docx=true` returns base64 Word output. Unknown fields and invalid equity are rejected.
- `GET /api/legal/sources/document?doc_id=...`: indexed PDFs within allowed legal directories only.

Swagger `/docs` provides exact schemas. Discover required contract fields from the catalogue rather than duplicating rules.

## Orchestrator

Ordinary questions route to `legal`. For drafting send a validated `legal_contract` object in `/api/chat`, alongside the shared profile. Structured drafting forces legal routing. `ChatResponse.artifacts` contains `{kind: "contract_draft", draft: ...}`. The composer does not paraphrase the document. Missing terms set `needs_clarification`; render `draft.missing_fields`, then resubmit confirmed complete fields.

The shared application's profile service supplies login data. This feature's profile form is per-page context, without authentication. User documents are factual inputs, not legal authorities or instructions. Confirm proposed values before drafting.

The dedicated `/api/legal/*` routes do not persist uploaded files or case text. The inherited `/api/chat` session store does persist conversation history and profiles under ignored `data/sessions/`. The integration owner must account for that storage and the shared authentication requirements.

## Evidence

Supplied WIPO PDFs and official Tunisian corpus → provenance → text extraction/selective OCR → structural chunks with source/page/article → BM25 + multilingual E5/Qdrant → legal/domain filtering → quoted claims → evidence review → cited answer or excerpt fallback.

Corrective retrieval is one extra local search. Optional `LEGAL_WEB_FALLBACK_ENABLED` adds one allowlisted WIPO lookup when local evidence or checked synthesis is insufficient. `wipo_research.py` reads only the legislative HTML body of fixed patent, trademark or copyright records, refuses redirects/arbitrary URLs, caps response size/time and caches for ten minutes. It sends no question, profile or attachment. Remote sources include URL/access time and undergo the same quote and claim checks. Unsupported topics, unavailable pages or insufficient evidence return research links/excerpts. Broad web search, amendment monitoring and verified current-law consolidation are not implemented.

Project-authored drafting structures retain identities, equity, dates and confirmed values. Optional refinement checks verbatim terms, new numbers, statutory assertions and changed meaning; failure retains the filled template. Research notes are separate from contractual obligations.

## Git

`law`, `legal-guidance` and `contract-drafting` are separate branch names; Git does not nest branches. Both cooperating modules are implemented together. The shared baseline was imported from `feat/orchestrator-rag` commit `b1af0e57b77359ad663d14dd4efbde92bb8c3e5d`, whose history differs from the original law root. Review against that baseline before integration. Do not blindly merge unrelated histories or overwrite the orchestrator branch.
