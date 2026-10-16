# Business plan (P4) change set

NEW   services/bp/**                      the bp service: app, mock, templates, guidance, prompts, eval, tests, Dockerfile, lockfile, README
NEW   backend/app/api/routes/bp.py         gateway routes: questionnaire, run (upload + answers), files, profile
NEW   backend/app/modules/bp/client.py     HTTP client for the bp service, uploads by sha256
NEW   backend/app/modules/orchestrator/profile.py   per-session profile the orchestrator collects
NEW   backend/tests/test_bp_gateway.py
NEW   frontend/bp.js
EDIT  backend/app/config.py, api/routes/{__init__,chat,aid}.py, graph/workflow.py,
      modules/registry.py, modules/router/domain_router.py, eval/datasets/routing_queries.jsonl
EDIT  frontend/{index.html,app.js,styles.css}
EDIT  docker-compose.yml, .env.example, .gitignore, docs/ARCHITECTURE.md

Run: uvicorn app.main:app --app-dir services/bp --port 8104   (service)
     uvicorn app.main:app --app-dir backend --port 8000        (gateway + site)
Tests: (cd services/bp && pytest)   (cd backend && pytest)

## v2: fixes after the 15 pitch test cases

- PDF headings are now detected per line (they were lost inside text blocks), so pitch PDFs split into sections.
- New `investor_pitch` template, chosen automatically when the document headings look like a pitch.
- New credibility assessment (`services/bp/app/agents/assessment.py`): red flags, weaknesses, strengths, verdict
  good / moderate / bad / high_risk. It says "verify this", never that someone committed fraud.
  On the 15 cases (docx and pdf, rules only, no model) it matches `answer_key.csv` 30/30. The weights were
  tuned on those same cases, so this is a development result, not accuracy on unseen plans.
  Run: `python eval/run_pitch_eval.py` from `services/bp`.
- The questionnaire is now a chat: `POST /v1/chat` (bp) and `POST /api/bp/chat` (gateway). One question at a time,
  skip anything, no model needed. The old form endpoint `/v1/questionnaire` is kept.
- Business plan tab: you pick upload OR chat first; the other is hidden.

## v3: reference data from the dataset pack

- `services/bp/data/benchmarks.sqlite` (your derived Damodaran tables) and `data/parameters.json` (IS 20%, CNSS, BCT rates, each with
  source, date and a `verified` flag; the secondary-source ones are marked unverified).
- `app/knowledge.py`: sector mapping (free text to Damodaran industry), parameters, and BM25 search over cited passages.
- `app/benchmark_check.py`: new "review this" signals: `margin_above_sector`, `loan_rate_low`, `tax_rate_unusual`, `payroll_without_charges`.
  Every message names the source and region. US margins are labelled as US.
- `scripts/build_knowledge.py <pack>`: builds `data/knowledge.sqlite` from `catalog/file_index.csv` (rows `use=rag`). Run it locally.
  Drafts then cite passages from the pack (tax code by article, accounting standards by paragraph, guides).
- Without `knowledge.sqlite` the module works as before; the benchmark checks only need `benchmarks.sqlite` and `parameters.json`.

## v4: UI fixes found by running the screen in a browser

- Chat: "we are creating it" and similar free answers are now understood; lists like "100000, 250000, 400000" are read as years.
- Local run: the bp service and the gateway now share `<repo>/data/uploads` by default. Before, the report was written to one folder and
  read from another, so the page showed only a bare summary. The gateway now says so if it ever happens again.
- Screen texts follow the chosen language (en, fr, ar). The verdict is only shown for uploaded documents.

## v6
- `scripts/mutation_test.py`: damages plans on purpose (delete a section, strip numbers, add a fraud sentence, a bad funding table, an inflated projection) and checks the module notices. Works on any folder of .docx plans, no labels needed.

## v7
- `scripts/fetch_test_plans.py` (download public plan pages into good/moderate/bad folders as .docx, labels chosen by you; SEC fraud releases go to fraud_language/) and `eval/run_folder_eval.py` (verdict vs folder name). `scripts/urls.example.csv` is a starting list: the labels in it are guesses, edit them.

## v9: professional layer for the generated plan
- plan_doc.polish: with a model, the founder's plain answers are rewritten as business-plan prose (prompt plan_writer@v1). Every figure is checked against the founder's facts; untraceable ones are marked "[to be confirmed by the founder]".
- plan_doc.advise: each section ends with "Advisor's notes" (criteria not covered yet + good-practice passage). Works without a model.
- Untested with a real Groq key: only a stub model was used in tests.

## v10: final institutional writer
- `prompts/bp/final_writer/v2.yaml`: one section per call with a {{section}} placeholder; the six-section skeleton, English-only rule, zero-hallucination marker and critic-bridging rules are unchanged from v1.
- `app/agents/final_writer.py`: `run_final_writer_agent(prompts, facts, current_plan, critique_report)` writes the six
  skeleton sections sequentially over async HTTP (httpx, temperature 0, seed 7, JSON-schema mode when configured).
  `writer.guard` runs on every section. Degrades per section (and as a whole) on no-key, timeout, bad JSON or an
  exhausted time budget; it never raises.
- `pipeline.py`: the critic pass (`app/agents/critic.py`) now runs inside `options.generate_plan` and feeds both
  the "critical weaknesses" page of the plan docx (previously dormant) and the final writer. The final writer is
  gated by `settings.llm_step("final_writer")`; its result is stored in `report["final_plan"]` of the `bp_report`
  artifact (contract unchanged). Inputs are masked before the calls and the result is unmasked after.

## v11: the final writer batches by default
- `prompts/bp/final_writer/v3.yaml`: all six sections in one reply (90-160 words each), same rules as v2.
- `app/agents/final_writer.py`: batch mode is the default — one call pays the context prefill once, which is most
  of the wait on a slow local model (measured estimate: ~4 min down to ~1.5-2 min on a local 70B, ~20-30 s on an
  8B). A section the batch reply dropped or malformed is topped up one call at a time with v2; if the batch call
  itself failed, top-ups run without retries so a dead endpoint is not hammered. `mode="sequential"` keeps the v2
  behavior. The result reports `mode` and `usage.calls`.
- `options.final_writer_mode` (`batch | sequential`, default `batch`) selects the strategy; anything else is
  `BAD_INPUT`. The report shape and the `bp_report` contract are unchanged.

## v12: the stack ships its own model (docker-compose)
- `docker-compose.yml` gains an `ollama` service (healthcheck, `ollama_models` volume, commented NVIDIA GPU block) and a
  one-shot `ollama-init` that pulls `LLM_MODEL_MAIN` (default `qwen2.5:7b`) on first boot. The bp container now waits for
  the pull (`service_completed_successfully`), so `docker compose up` is ready only when the model is usable. First boot
  downloads ~4.7 GB; afterwards it is cached in the volume.
- bp defaults in compose now point at the bundled Ollama (`LLM_BASE_URL=http://ollama:11434/v1`, `LLM_API_KEY=ollama`);
  hosted OpenAI-compatible APIs stay one env override away. The gateway gets `BP_TIMEOUT_S=600` to match the bp budget so
  local-model plan generation is not cut off at 90 s. Deterministic-only run: `docker compose up api bp --no-deps`.
- `.env.example`: Ollama-first defaults, and the real-looking Groq key that was committed there is replaced by a
  placeholder (it remains in git history — rotate it if it was live).

## v13: Groq-first env template
- `.env.example` now ships with the hosted Groq block active (placeholder key, `llama-3.3-70b-versatile` /
  `llama-3.1-8b-instant`, fast timeouts) and the local-Ollama block commented with switch instructions. One active
  block at a time — the previous version allowed both pairs to be present, where last-one-wins decided silently.
- With the Groq block active under Docker, start `api bp --no-deps`: the bundled Ollama would otherwise be pulled
  (4.7 GB) and awaited before bp starts, only to go unused.
