# Legal component validation

Validated locally on 16 October 2026 with Python 3.12.10. These are software and retrieval checks, not certification of legal accuracy or current law.

## Automated checks

- 83 tests pass with the local corpus index. The suite includes the team's original API/orchestrator regressions, ten contract types in three output languages, Word package/content checks, missing-intake handling, ownership totals, unilateral NDA roles, rejected fabricated citations, translation numeric and patent-terminology preservation, bounded WIPO fallback, private document intake, page-range limits and citation page offsets.
- A fresh-clone configuration without generated indexes or model weights is also tested; only the two index-dependent integration checks are skipped there.
- `pip check` reports no broken requirements. `node --check frontend/legal.js` passes.
- GitHub Actions runs the no-key/no-model suite for the legal-guidance branch and integration pull requests. Its actions are pinned to verified official release commits. A workflow definition alone does not prove a remote run passed; inspect the check on the pushed commit.

## Real local resources

- Quantized Qwen3 1.7B via llama.cpp CPU runtime, with pinned model revision and SHA-256 verification. No paid API key is needed for the tested local setup.
- Multilingual E5-small quantized ONNX embeddings, BM25 and embedded Qdrant. Nine smoke questions cover English, French and Arabic patent/trademark queries, copyright and the startup label. The expected document is found in the first five results for all nine questions. This small source-hit test is not a general legal-answer benchmark.
- Arabic, French and English Tesseract OCR is installed. The watermarked Arabic commercial code uses Arabic-only OCR and input thresholding; the original PDFs are unchanged. OCR text remains machine transcription requiring review.
- The local corpus includes 29 legal documents and 7,230 legal passages. The extraction report identifies 34 unreadable or sparse pages, which are excluded from evidence. Exact passage counts and OCR page counts are available from `/api/legal/status` and `data/index/report.json` after each rebuild.
- The six supplied private contract examples all pass local intake. The 231-page consortium agreement is read in bounded page ranges, and long extracted text is explicitly truncated. No private text or original contract is committed.

## Live and interface checks

Local generation is exercised with public-source English, French and Arabic questions. Exact quotes, citation references, output language, numeric preservation and a second evidence-review call control the generated answer. Unsupported generation returns evidence or abstains. `data/legal-generation-smoke.json` records the actual latest modes, answers and latencies.

A synthetic complete NDA passes local AI refinement and Word export. All ten agreement types also pass deterministic export tests in all three languages. Founder identities, percentages, dates and confirmed terms remain fixed. The browser checks cover missing intake, a complete NDA preview, profile-to-intake copying and preserving terms while switching agreement types.

Live allowlisted WIPO pages return readable legislative HTML for patents, trademarks and the copyright amendment. Navigation is excluded. The fallback records URL/access time and does not send user questions, profiles or documents to WIPO. It does not establish whether a provision is the current consolidated rule.

On 16 October 2026, an end-to-end forced-empty local search used the live WIPO patent page and produced a quoted, evidence-reviewed English answer through the local model. Its trace records local retrieval, one correction, WIPO research and grounding. The report is `data/qa/live-wipo-fallback.json`.

The final retrieval check finds the patentability provision (Article 2) first for all three patent-language cases. The source-hit smoke result remains 9/9. GitHub Actions [run 38874954243](https://github.com/eyahamdidev/Law_Rag/actions/runs/38874954243) passed for feature commit `7583319`; the Windows-only dependency lock entries now have platform markers so Linux CI can install them.

## Limits and integration review

- Supplied law editions are not certified current. The agent must not be presented as a final legal opinion or a guarantee that a contract is valid.
- Drafts are unsigned, project-authored drafting aids requiring review of jurisdiction, company documents, mandatory rules, authority and agreed terms.
- DOCX ZIP/content checks pass. Full visual Word rendering was not completed because this Windows runtime does not include the document renderer's LibreOffice executable. Do not describe visual layout as verified.
- Docker files are provided as a scaffold; a production container deployment was not validated. Windows runtime preparation scripts are not a Linux model-server installer.
- Hosted Groq/Gemini settings are inherited adapters and were not live-tested with account credentials. The validated generation path uses the local model.
- Dedicated legal endpoints are stateless. The inherited shared chat service stores history/profiles in ignored `data/sessions/`; authentication and retention must be addressed by the integration owner.
- The feature imports the shared backend baseline from `feat/orchestrator-rag` commit `b1af0e57b77359ad663d14dd4efbde92bb8c3e5d`. Review the legal changes against that baseline when integrating; its Git history differs from the original law root.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest backend -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\evaluate_legal_retrieval.py
.\run-agent.cmd
.\.venv\Scripts\python.exe scripts\smoke_legal_generation.py --api-url http://127.0.0.1:8000
```

Stop the API before the direct retrieval evaluation or any index rebuild, because embedded Qdrant permits one process at a time. Keep generated reports, CSVs, OCR caches, sessions, model weights and `.env` outside Git.
