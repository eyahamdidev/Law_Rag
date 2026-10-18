# bp: business plan service (P4, port 8104)

Reviews a business plan, scores it section by section, runs deterministic financial checks, and drafts what is missing — including a full institutional-grade plan (`generate_plan`) written by the final writer. It is one stateless HTTP service. Anyone can talk to it: the backend gateway today, n8n or any other client tomorrow. Nothing in this document requires special client code.

**Two ways in, usable together**, plus what the orchestrator already knows:

| Source | How it arrives | Precedence |
| --- | --- | --- |
| Guided questionnaire or chat | `options.answers` `{question_id: answer}` | 1st |
| Orchestrator profile (chat, aid tab, intake) | `profile` | 2nd |
| Uploaded plan (docx, pdf, xlsx, txt) | `file_ref` (sha256 in the shared uploads folder) | 3rd for profile facts. For figures in tables the plan wins and the difference is reported as `source_conflict`. |

Every disagreement becomes a `profile_conflict` or `source_conflict` signal. Nothing is overwritten silently.

---

## Quick start

```
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8104          # real service
uvicorn mock.main:app --port 8104         # mock, fixtures only (for client dev)
pytest                                    # 49 tests
python -m eval.run_eval                   # synthetic evaluation suites
python scripts/ingest_guidance.py         # optional: guidance into Qdrant bp__guidance (needs Ollama bge-m3)
python scripts/build_knowledge.py <pack> --out data/knowledge.sqlite   # optional: reference-data search
```

Without `LLM_API_KEY` the service still works end to end: keyword rubric for section scoring, deterministic financial checks, drafts built from the founder's own answers. `llm_unavailable` is reported as an info signal. No step ever blocks on a model being up.

### One-command stack with Docker

From the repo root:

```
docker compose up --build           # gateway :8000 + bp :8104 + bundled Ollama :11434
```

The stack ships its own model server: an `ollama` service plus a one-shot `ollama-init` that pulls `LLM_MODEL_MAIN` (default `qwen2.5:7b`) into a named volume. The bp container waits for the pull, so when `up` settles, everything works — the target machine needs Docker and nothing else.

- First boot downloads the model (~4.7 GB for qwen2.5:7b); afterwards it is cached in the `ollama_models` volume. Pin a different model with `LLM_MODEL_MAIN` in `.env` (keep it 7–8B class for CPU-only hosts; a 70B is ~40 GB and needs a GPU).
- GPU hosts: uncomment the `deploy.resources` block on the `ollama` service (needs the NVIDIA Container Toolkit).
- Deterministic-only, no model download: `docker compose up api bp --no-deps` (bp then reports `llm_unavailable` and runs the rule-based path).
- Hosted model (e.g. Groq) with the Groq block active in `.env`: start only the app containers — `docker compose up api bp --no-deps`. A plain `docker compose up` would still pull and await the bundled Ollama model for nothing.
- The gateway's `BP_TIMEOUT_S` (default 600 in compose) matches the bp budget so long `generate_plan` runs on a local model don't get cut off at the gateway.

---

## HTTP API

### `GET /health`
Liveness plus `llm_configured` / `llm_reachable` (cached 30 s).

### `GET /v1/meta`
Contract version, endpoints, modes, configured models per role, prompt versions on disk, corpus sizes, timeout budget. The orchestrator reads this at startup.

### `POST /v1/run` — the main entry point

Request body (frozen contract, spec section 2.2):

```json
{
  "request_id": "any-opaque-id",
  "workspace": "bp",
  "lang": "fr",                       // fr | ar | en
  "file_ref": "<64-hex sha256>",      // optional uploaded plan
  "profile": {"sector": "boulangerie"},
  "options": {"mode": "review"},
  "question": "quelles primes pour une startup ?"
}
```

`question` is only used for handoff detection: statute wording hands off to `law`, program wording (BFPME, subvention, Startup Act...) hands off to `aid`. It is not answered here.

**Options** (all optional):

| Option | Values | Default | Effect |
| --- | --- | --- | --- |
| `mode` | `review`, `draft_section` | `review` | Full review, or draft specific sections |
| `answers` | `{question_id: value}` | — | Questionnaire answers (ids from `/v1/questionnaire`) |
| `template` | `bfpme_creation`, `bfpme_extension`, `giz` | by stage | Which section skeleton to judge against |
| `section_id` | template section id or `missing` | — | With `draft_section`: which section(s) to draft |
| `draft_missing` | bool | false | In review mode: also draft missing/weak required sections |
| `generate_plan` | bool | false | Produce a full plan docx (critic → composer → final writer) |
| `final_writer_mode` | `batch`, `sequential` | `batch` | Six sections in one model call vs one call per section |
| `seed` | integer | `7` | Final-writer seed; the frontend Regenerate button sends a fresh random one to re-roll the plan on the same inputs |
| `parser_mode` | `keywords`, `llm`, `auto` | `auto` | How the uploaded plan is segmented |
| `rubric_style` | `plain`, `cot` | `plain` | Section scoring prompt style |
| `masking` | bool | true | Mask names/ids before any model call (see Privacy) |
| `llm` | bool | true | `false` forces the fully deterministic path |

Invalid values come back as `400 BAD_INPUT`, not silent defaults.

**Response** (frozen contract — never extended with bp-specific fields):

```json
{
  "request_id": "...", "module": "bp", "status": "ok",
  "answer": "Complétude du plan : 62/100 ...",
  "signals": [{"id": "bp-dscr-low", "kind": "...", "severity": "review", "message": "Review this: ...", "evidence": {...}, "source": "rule"}],
  "citations": [{"doc_id": "S1", "passage_id": "...", "code_or_title": "...", "score": 0.0}],
  "artifacts": [{"kind": "docx", "file_ref": "<sha256>", "label": "business_plan"}],
  "handoff": null,
  "trace": [{"step": "final_writer", "ms": 41200, "model": "...", "prompt_id": "final_writer@v3"}],
  "latency_ms": 45000, "error": null
}
```

Artifacts by label:

| Label | Kind | When |
| --- | --- | --- |
| `bp_report` | json | always — the full structured result (read this, not the `answer` string) |
| `bp_review` / `bp_draft` | docx | always — the human-readable review report |
| `business_plan` | docx | `generate_plan: true` — the generated full plan |
| `projection_chart` | png | when a revenue projection exists |

The `bp_report` JSON contains: `mode`, `template`, `input.methods`, `context` (merged values with `provenance` per key, `conflicts`), `assessment` (credibility verdict), `benchmarks`, `completeness` (per-section scores), `financials` (derived model + `origin`), `drafts`, `unmapped`, `signals`, `privacy` (masking on/off, counts, whether a model was used), `usage`, `summary_text`, and with `generate_plan` also `generated_plan` and `final_plan`.

`final_plan` (the institutional six-section rewrite) looks like:

```json
{
  "method": "model",                  // model | partial | unavailable
  "mode": "batch", "model": "...", "prompt_id": "final_writer@v6",
  "sections": [
    {"id": "executive_summary", "title": "Executive Summary", "text": "...", "flagged": [], "status": "ok"}
  ],
  "open_items": ["What is the CEO's relevant experience?"],
  "verdict": "Mid as it stands, because ...",
  "usage": {"calls": 1}
}
```

Sections have status `ok`, `skipped` (no model configured) or `error` (with the reason). `flagged` lists figures the guard marked. With the v6 batch prompt the reply can also carry `open_items` (every `[NEEDED: ...]` placeholder question from the sections, ordered) and a one-line honest `verdict`; both are absent when empty or on the per-section top-up path. The six ids, in order: `executive_summary`, `market_opportunity`, `competitive_advantage`, `go_to_market`, `operational_roadmap`, `financial_strategy`.

### `POST /v1/questionnaire` (additive, pending P5 approval)

Body: `{lang, profile, answers, template}`. Returns every question with status `answered | prefilled | missing | invalid`, its current value, source, parse error, and which sections it feeds — everything a UI needs to render the form once and prefill what the orchestrator already knows.

### `POST /v1/chat` (additive, pending P5 approval)

Body: `{lang, profile, state, message, action}`. One turn of the conversational questionnaire. **The caller owns the state**: send back the `state` you got last time. Response:

```json
{
  "messages": ["Great. What sector is Medilink in?"],
  "state": {"...": "pass this back on the next call"},
  "answers": {"project_name": "Medilink"},
  "asking": "sector", "type": "text",
  "chips": ["Bakery", "SaaS"], "actions": [{"action": "skip", "label": "Skip"}],
  "phase": "core", "ready_to_review": false,
  "progress": {"core_total": 12, "core_left": 9}
}
```

When `ready_to_review` is true (or action `finish`), feed `answers` into `/v1/run`.

### `POST /v1/eval`

Body: `{suite: "all|financial|sections|writer|merge", seed, n}`. Runs the synthetic evaluation suites and returns pass rates.

### Error codes

`BAD_INPUT` 400 · `UNSUPPORTED_FILE` 415 · `MODEL_UNAVAILABLE` 503 · `TIMEOUT` 504 · `INTERNAL` 500. The whole run is wrapped in `BP_TIMEOUT_S`; `/v1/run` returns `TIMEOUT` rather than hanging.

---

## How it works under the hood

One synchronous pipeline per request (`app/pipeline.py`). The FastAPI layer runs it in a worker thread with a hard timeout.

```
intake → parser → [vision] → context merge → section combine → financial checker
      → benchmarks → reviewer → assessment → [drafts] → signals
      → [chart] → [critic → plan docx → final writer] → report docx → bp_report.json
```

| Step | What it does | Model? |
| --- | --- | --- |
| intake | Reads the file: docx/pdf/xlsx/txt, text layer, scanned pages, headings | no |
| parser | Segments the plan into template sections, extracts financial tables and facts. `parser_mode=auto` tries keywords and uses the model only for unclear segments. Scanned pages are flagged, never used in checks (a vision model may read them read-only, with a warning). | optional |
| context merge | Merges profile + answers + document facts with precedence and conflict signals | no |
| financial checker | Plain Python: derives EBITDA, payroll ratio, DSCR, break-even, cash; emits `high`/`review` signals. No model, ever. | **no** |
| benchmarks | Compares margins, loan rate, tax rate against reference-sector benchmarks; every signal names its source ("US reference data...") | no |
| reviewer | Scores each template section against a rubric (0–100). Quotes must exist in the plan. Keyword rubric without a model. | optional |
| assessment | Credibility verdict on the whole document (fraud-pattern flags, structure ratios) | optional |
| drafts | `draft_section` mode / `draft_missing`: writes missing sections from the founder's answers; figures not in the inputs are marked, and unsupported claims become `[NEEDED: ...]` placeholders instead of being invented (writer@v2, same no-fabrication contract as final_writer v6) | optional |
| critic | With `generate_plan`: collects the weaknesses of the current plan → feeds the docx "critical weaknesses" page and the final writer | optional |
| plan docx | Composes the full plan from questionnaire values, polishes it with guidance passages, adds advisor notes | optional |
| **final writer** | The institutional six-section rewrite → `report.final_plan` (detailed below) | optional |
| chart / docx / json | Projection chart, review docx, `bp_report` json. Always produced. | no |

### The final writer

The prompt library (`prompts/bp/final_writer/`) holds six versions:

- **v6 (batch, default)** — one call, same mechanics and evidence hierarchy as v5, upgraded with the **founder-writer hard rules**: an internal fact table (every value tagged `founder_said` / `derived` / `assumption` / `missing`) built before writing; a strict **no-fabrication contract** — when information is missing, the text carries a `[NEEDED: <exact question>]` placeholder and the claim is never written, not even with a caveat (v5's "state the claim, mark the number" pattern leaked invented claims like "our CEO has over 10 years of experience"); **bottom-up market sizing only**; **no professionalised claims** (founder experience, traction, LOIs, partnerships are written only if evidenced); realism over weak numbers; and a final self-check that deletes any sentence asserting a fact outside the fact table. The reply also carries **`open_items`** (every `[NEEDED]` question, ordered) and a one-line honest **`verdict`** ("Strong / Mid / Weak as it stands, because ...").
- **v5 (batch)** — one call, same mechanics as v4, governed by the **evidence-grounded specification**: a six-level source hierarchy (confirmed founder info > verified uploads > verified external evidence > calculated outputs > founder estimates > labeled illustrative assumptions) with the earlier AI draft explicitly demoted to non-evidence; source conflicts are preserved and flagged, not silently resolved; a per-section six-step writing procedure (extract → review → draft → classify evidence → cross-validate → editorial QC); financial writing rules (use the calculation engine's outputs, never equate accounting profit with cash, state limitations when the model is incomplete); a verbatim banned-generic-claims list; and an **eight-point final validation** gate. The spec's six evidence classes map onto the existing marker instead of a new output field, per the spec's own "do not alter the output schema" rule. Kept for history and A/B against v6.
- **v4 (batch)** — one call, same batch mechanics as v3, but the writer runs under the **master consultant specification**: the expert-consultant persona, ten non-negotiable rules (zero fabrication, marker instead of guessed numbers, financial integrity and cross-section consistency, defensible claims, honest presentation of unrealistic assumptions, professional objectivity, confidentiality) and a **seven-point final quality-control gate** the model must verify before returning. Kept for history and A/B against v5.
- **v3 (batch)** — one call. The full persona (institutional consultant; corporate English only; unit economics and TAM/SAM/SOM, no marketing fluff; zero unflagged figures), the founder's facts, the current plan and the critic's weaknesses go in once; all six sections come back as one JSON array. A slow local model pays the context prefill **once** instead of six times: ~4 min → ~1.5–2 min on a 70B, ~20–30 s on an 8B (estimates from prefill arithmetic, not measured runs). Kept for history and A/B against v4.
- **v2 (per-section)** — one call per section, "Write ONLY section X". Used as the **top-up** for sections the batch reply dropped, truncated or returned malformed, and for `final_writer_mode: "sequential"`.
- v1 — original all-in-one variant, kept for history.

Mechanics (`app/agents/final_writer.py`):

1. Facts, plan text and critique are **masked** (names → `[[NAME_1]]`, fiscal ids, IBAN/RIB, e-mails, phones) before leaving the process; the result is unmasked afterwards.
2. The call goes over plain `httpx.AsyncClient` (no SDK), `temperature: 0`, `seed` (default `7`; the **regenerate** option sends a fresh random seed to re-roll the same inputs — the frontend "Regenerate" button, `seed` form field on the gateway, `options.seed` here), JSON schema (or JSON object) mode — deterministic per input + seed.
3. Whatever comes back passes through `writer.guard`: every number that cannot be traced to the facts, the plan, or the critique gets `[to be confirmed by the founder]` appended mechanically. The model cannot present an invented figure as fact, even if it tries.
4. Sections missing from the batch reply are re-written one by one with v2 (no retries after a failed batch, so a dead endpoint is hit at most 7 times).
5. Any total failure leaves `final_plan` absent or `method: "unavailable"` — the plan docx and the rest of the report are never lost.

**Does batching cost quality?** Same rules, same guard, same inputs — the output contract is identical. Two real differences: the model sees all six sections at once, so cross-section coherence improves (the executive summary cannot contradict the financials it just wrote); and a truncated long reply is caught and topped up, but a topped-up section was written without seeing its siblings. On small models, per-section prose can be a touch thinner in batch mode. Deterministic checks are unaffected either way. `final_plan.mode` says which path produced a result, and with temperature 0 + fixed seed you can A/B `batch` vs `sequential` on identical inputs and diff the six sections.

### Graceful degradation and step gating

- No key / unreachable model → keyword rubric, deterministic checks, answer-based drafts, `llm_unavailable` info signal.
- `BP_LLM_STEPS=parser,reviewer` (any comma list) restricts which steps may call a model at all. Step names: `parser, reviewer, assessment, vision, drafts, plan_writer, critic, final_writer`. Useful on a slow local box: keep the review fast and rule-based and spend the budget on the final writer only (`BP_LLM_STEPS=final_writer`).
- `options.llm: false` forces the deterministic path for one request regardless of env.

### Privacy

Names (project, founders), fiscal ids, RIB/IBAN, e-mails and phone numbers are masked before **any** model call and restored afterwards — for the reviewer, the critic, the plan writer and the final writer alike. `privacy.masked_counts` in the report says how much was masked and `model_used` whether a model saw anything. `masking: false` disables it for a request, and the report says so. The fiscal-id pattern is permissive until the exact Tunisian format is confirmed.

---

## Integrating with the orchestrator (gateway)

The rules that make this work:

1. **HTTP + JSON only.** The gateway (`backend/app/modules/bp/client.py`) never imports bp code. Any other orchestrator follows the same pattern — that is the whole integration contract.
2. **The wire contract is frozen** (`app/contract.py`, `CONTRACT_VERSION 1.0.0-bp-vendored`). Business-plan-specific data travels in `options` (request) and inside the `bp_report` JSON artifact (response) — never as new response fields.
3. **Files travel by reference.** An upload is stored once as `<UPLOADS_DIR>/<sha256>`; requests carry the 64-hex digest only. Artifacts come back the same way.

```
frontend ──HTTP──▶ gateway (backend, :8000) ──HTTP──▶ bp service (:8104)
                        │                                   │
                        └──────── same UPLOADS_DIR folder ──┘
                               /data/uploads/<sha256>
```

The gateway already wraps everything (`backend/app/api/routes/bp.py`):

| Gateway route | Calls | Notes |
| --- | --- | --- |
| `POST /bp/questionnaire` | `/v1/questionnaire` | adds the session profile |
| `POST /bp/chat` | `/v1/chat` | adds the session profile |
| `POST /bp/run` | `/v1/run` | multipart form: `file` + fields; stores the upload, returns `{response, report}` where `report` is the parsed `bp_report` |
| `GET /files/{ref}?kind=docx&name=...` | — | downloads any artifact by sha256 |
| `GET/PUT/DELETE /profile` | — | session profile, keyed by the `X-Session-Id` header |

The session loop: the gateway keeps a per-session profile (`backend/app/modules/orchestrator/profile.py`), injects it into every bp call, and after a questionnaire run merges the founder-confirmed fields (`stage`, `sector`, `legal_form`, `startup_label`, `governorate`, `export_status`, `headcount`, `avg_gross_salary`, `funding_instrument`) back into the session — so the next tab (aid, law) already knows them.

To point the gateway at the service: `BP_SERVICE_URL=http://localhost:8104`, and **both processes must resolve `UPLOADS_DIR` to the same folder**. Run from the repo this is automatic (`<repo>/data/uploads`); in Docker, mount the same volume into both containers.

A new orchestrator — or n8n acting as one — needs exactly: this base URL, a sha256-addressable shared folder (or the gateway for uploads), and the contract above.

---

## Using it from n8n

n8n is just another HTTP client — the same endpoints, no plugin needed. Two practical constraints shape any workflow:

- **`/v1/run` is synchronous.** With `generate_plan` and a local LLM it can take minutes. Raise the HTTP Request node timeout above `BP_TIMEOUT_S`, or limit the LLM steps so runs stay fast.
- **The chat is stateless.** Whoever calls `/v1/chat` stores and returns `state`. In n8n that means carrying it through the workflow (Set/Code node) or persisting it between executions.

### Flow 1 — conversational questionnaire

```
Webhook ─▶ HTTP Request: POST {BP_URL}/v1/chat    body: {lang, profile, state, message, action}
        ─▶ Respond to Webhook (return messages, chips, actions, state)
```

- First call: no `state` (or `{}`), `message` null → greeting + first question.
- Every turn: put the user's reply in `message` (or `action: "skip"` / `"finish"` / `"more"` from the chips) and **the previous `state` back in**.
- Stop when `ready_to_review` is `true`. Keep the final `answers` object for the run.

### Flow 2 — review or full plan generation

Two variants, depending on where uploads live:

- **Through the gateway (recommended — it handles the file for you):** HTTP Request node → `POST {GATEWAY}/bp/run`, body type **form-data**: `file` (binary, from a previous node), `mode=review`, `generate_plan=true` (or `false`), `answers` (JSON string), `lang`. Response: `{response, report}` — `report` is already the parsed `bp_report`.
- **Direct to the bp service:** the service only accepts a `file_ref` (sha256), not bytes. Either write the file into the shared `UPLOADS_DIR` yourself (Code node) and send its sha256 as `file_ref` in a JSON body to `/v1/run`, or simply go through the gateway.

### Flow 3 — fetch the deliverables

`GET {GATEWAY}/files/{file_ref}?kind=docx&name=Business-Plan` for the docx/png artifacts listed in `response.artifacts` (pick by `label`). The `bp_report` JSON comes embedded in the gateway response, so no extra fetch is needed there.

### Gotchas

- `answers` and `profile` are **JSON strings** inside multipart form data — stringify them.
- The bp service answers errors in contract shape (`status: "error"`, `error.code`); the gateway converts them to HTTP status codes. Branch on `status` or the HTTP code.
- Don't blindly retry `/v1/run` on timeout — a run may still be burning the model behind the timeout. Check `/health` first.
- `final_plan` is absent when the model was never reachable — the review and the plan docx still exist. Treat it as an optional layer, not a guaranteed one.

---

## Templates, guidance, knowledge

- `templates/` — derived skeletons (`bfpme_creation`, `bfpme_extension`, `giz`), built by `scripts/build_templates.py`. The official BFPME/GIZ models are legacy `.xls`/`.doc` and could not be read; each template says `verified_against_official_model: false`. Convert the files to `.xlsx`/`.docx`, compare headings, then update the script.
- `guidance/` — hand-written rubric guidance per section; no model needed.
- `scripts/ingest_guidance.py` — optional: embeds guidance into Qdrant (`bp__guidance`, needs Ollama bge-m3) so writer drafts can cite passages. Without it, retrieval falls back to lexical matching.
- `scripts/build_knowledge.py` — builds `data/knowledge.sqlite` from a reference-data pack (sector mapping, benchmarks, statute index) with a small local search index.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `UPLOADS_DIR` | `<repo>/data/uploads` when run from the repo, else `/data/uploads` | Shared artifact store; **must match the gateway's** |
| `BP_TIMEOUT_S` | `60` | Whole-run budget; raise for local models with `generate_plan` |
| `LLM_BASE_URL` | Groq API | OpenAI-compatible endpoint (local Ollama: `http://localhost:11434/v1`) |
| `LLM_API_KEY` | empty | Empty ⇒ fully deterministic mode |
| `LLM_MODEL_MAIN` / `_FAST` / `_VISION` / `_EMBEDDER` | from `MODELS_CONFIG` | Per-role model override (e.g. `qwen2.5:7b`) |
| `MODELS_CONFIG` | `<repo>/config/models.yaml` | Role→model map (`llm_main`, `llm_fast`, `llm_vision`, `embedder`) |
| `LLM_TIMEOUT_S` | `45` | Per-model-call timeout; raise together with `BP_TIMEOUT_S` |
| `LLM_JSON_MODE` | `json_object` | `json_schema` where the model supports strict output |
| `LLM_CACHE_PATH` | `.cache/llm_cache.sqlite` | Deterministic call cache (temp 0, seed 7) |
| `BP_LLM_STEPS` | `all` | Comma list of steps allowed to call a model |
| `BP_LLM` | `auto` | `off` forces no-model mode |
| `BP_VECTOR_STORE` | `auto` | `off` disables Qdrant guidance retrieval |
| `OLLAMA_BASE_URL` / `QDRANT_URL` / `MLFLOW_TRACKING_URI` | docker service names | Infrastructure endpoints |

## Evaluation

- `pytest` — 49 tests, all offline (no network, model forced off).
- `python -m eval.run_eval` / `POST /v1/eval` — synthetic suites: `financial`, `sections`, `writer`, `merge`.
- `python -m eval.run_pitch_eval` — pitch-case answer-key check.
- Synthetic numbers are not results on real plans; rubric agreement needs a hand-scored sample of about 10 plans.

## Honest limits

- **Templates are derived skeletons** (`verified_against_official_model: false`) — see Templates above.
- Thresholds in `app/financial.py` (DSCR 1.2, growth, payroll band, 20 % tax) are rules of thumb that make the module say "review this". They are not BFPME or legal criteria. Confirm the tax rate against the current finance law.
- No OCR. Scanned pages are flagged; a vision model may read them, but those rows never enter checks.
- Prompt `metric_before` / `metric_after` are `null` until real benchmark runs exist.
- The batch-mode latency figures (~1.5–2 min on a 70B) are prefill arithmetic, not measurements.
- The final writer writes in English only (per spec); the review report itself follows `lang`.
