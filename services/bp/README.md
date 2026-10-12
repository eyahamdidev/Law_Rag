# bp: business plan service (P4, port 8104)

Reviews a business plan and drafts missing sections. **Two ways in, usable together**, plus what the orchestrator already knows:

| Source | How it arrives | Precedence |
| --- | --- | --- |
| Guided questionnaire | `options.answers` `{question_id: answer}` | 1st |
| Orchestrator profile (chat, aid tab, intake) | `profile` | 2nd |
| Uploaded plan (docx, pdf, xlsx, txt) | `file_ref` (sha256 in `/data/uploads`) | 3rd for profile facts. For figures in tables the plan wins and a difference is reported as `source_conflict`. |

Every disagreement becomes a `profile_conflict` or `source_conflict` signal. Nothing is overwritten silently.

## Endpoints
`GET /health`, `GET /v1/meta`, `POST /v1/run`, `POST /v1/eval` (the four from spec 2.3) and one additive helper, `POST /v1/questionnaire` (question list with `answered | prefilled | missing | invalid` per question). The helper needs P5's approval in the contract review.

`/v1/run` modes: `review` (default) and `draft_section` (`options.section_id` = a template section id, or `missing`). Other options: `answers`, `template` (`bfpme_creation | bfpme_extension | giz`, default by stage), `draft_missing`, `parser_mode` (`keywords | llm | auto`), `rubric_style` (`plain | cot`), `masking` (default true), `llm` (false forces the deterministic path).

Outputs: `answer` (summary or drafts), `signals[]`, `citations[]` (guidance passages used by the writer), `artifacts[]` = `png` projection chart, `docx` report, `json` labelled `bp_report` (full structured result: sections, financials, drafts, provenance). `handoff` is set only for statute questions (to `law`) or program questions (to `aid`).

## Chain
parser (keywords, then model for unclear segments) → section reviewer (rubric; quotes must exist in the plan) → **financial checker (plain Python, no model)** → writer (figures not in the inputs are marked `[to be confirmed by the founder]`, enforced after the model by a guard, one retry) → chart maker → docx.

Without `LLM_API_KEY` the service still works: keyword rubric, deterministic checks, drafts built from the founder's answers. `llm_unavailable` is reported as an info signal.

## Run
```
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8104          # real service
uvicorn mock.main:app --port 8104         # mock, fixtures only
pytest                                    # 25 tests
python -m eval.run_eval                   # synthetic evaluation suites
python scripts/ingest_guidance.py         # optional: guidance into Qdrant bp__guidance (needs Ollama bge-m3)
```
Env: `UPLOADS_DIR`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_JSON_MODE`, `OLLAMA_BASE_URL`, `QDRANT_URL`, `MODELS_CONFIG` (roles `llm_main`, `llm_fast`, `llm_vision`, `embedder`; defaults in `app/config.py` until the freeze), `MLFLOW_TRACKING_URI`.

## Honest limits
* **Templates are derived skeletons.** The official BFPME and GIZ models are legacy `.xls`/`.doc` and could not be read. Each template says `verified_against_official_model: false`. Convert the files to `.xlsx`/`.docx`, compare headings, then update `scripts/build_templates.py`.
* Thresholds in `app/financial.py` (DSCR 1.2, growth, payroll band, 20 % tax) are rules of thumb that make the module say "review this". They are not BFPME or legal criteria. Confirm the tax rate for the current finance law.
* No OCR in this module. Scanned pages are flagged. A vision model may read them, but those rows are never used in checks.
* Prompt `metric_before` / `metric_after` are `null` until real benchmark runs exist.
* Synthetic evaluation numbers are not results on real plans. Rubric agreement needs a hand-scored sample of about 10 plans.
* Privacy: names, fiscal ids, RIB/IBAN, e-mails and phone numbers are masked before any model call and restored afterwards. The fiscal-id pattern is permissive until the team confirms the exact format. Masking can be switched off per request and the report says so.
