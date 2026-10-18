# Tunisian Legal & Financial Assistant

Multi-agent assistant for Tunisian founders. A LangGraph orchestrator plans which agents to call (legal, grants, business plan, fraud, marketing), runs them in parallel over a cited RAG index of Tunisian official texts and funding programmes, verifies every citation and claim, and composes one answer in French, Arabic or English. Uploaded PDFs, scans and photos are read with text extraction and vision OCR. n8n automates around it: a chat webhook, a founder intake form and a daily health check.

- How it works, and how to plug in your agent: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Results: [docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md), [docs/ROUTING_EVAL_HELDOUT.md](docs/ROUTING_EVAL_HELDOUT.md)
- Prompts and their iterations: [docs/PROMPT_LIBRARY.md](docs/PROMPT_LIBRARY.md)

## Quick start (Windows)

Four steps. The first time takes 15-20 minutes, plus the search index (step 3).

### 0. What you need

| | Why | Where |
| --- | --- | --- |
| **Git** and **Git LFS** | one large law PDF is stored with LFS | https://git-scm.com, https://git-lfs.com |
| **Python 3.12** (64-bit) | runs all three services (3.10, 3.11 and 3.13 also work for some of them; the installer picks) | https://www.python.org/downloads/ (tick **Add python.exe to PATH**) |
| A free **Groq** key and a free **Gemini** key | the language models; use **your own** (limits are per account) | https://console.groq.com/keys, https://aistudio.google.com/apikey |
| About **8 GB** free disk | Python packages, models (2.2 GB, downloaded once), index | |
| Optional: **Docker Desktop** | only for n8n | https://www.docker.com/products/docker-desktop/ |
| Optional: **Tesseract OCR** (French + English) | only to read the words on invoice stamps | https://github.com/UB-Mannheim/tesseract/wiki |

### 1. Get the code

```powershell
git lfs install
git clone --branch integration/agents https://github.com/eyahamdidev/Law_Rag.git
cd Law_Rag
```

Already cloned? `git fetch origin`, `git checkout integration/agents`, then `git lfs pull`.

### 2. Install: double-click `install.cmd`

Or type `install` in a terminal opened in the `Law_Rag` folder. It:

1. checks the law PDFs were downloaded by Git LFS;
2. creates three Python environments, because the services need different library versions: `.venv` (main app, `requirements.txt`), `.venv-fraud` (`requirements-fraud.txt`), `.venv-bp` (`services/bp/requirements-dev.txt`);
3. creates `.env` from `.env.example` and asks for your Groq and Gemini keys (`.env` is git-ignored: keys never leave your PC);
4. offers to build the search index (step 3);
5. runs the tests (124, about 30 s, no key or index needed).

Run it again any time (after a `git pull`, for example): existing environments are updated and your `.env` is kept.

With an NVIDIA (or other DirectX 12) GPU, `install.cmd -Gpu` makes search much faster. On laptops with Intel + NVIDIA graphics the NVIDIA card is usually device 1 (the default in `.env`); if nothing gets faster, set `EMBEDDING_DEVICE_ID=0` in `.env`.

### 3. The search index (once)

The index (`data/index/` and `data/qdrant/`) is generated from the PDFs and is not on GitHub. Either:

- **copy it** (fastest): ask a teammate for a zip of their `data\index` and `data\qdrant` folders (about 270 MB) and unzip both into your `Law_Rag\data\` (copy the whole `qdrant` folder, not a collection inside it); or
- **build it**: `install.cmd -BuildIndex`, or answer `y` when install asks. About **60 minutes on a CPU**, 10 on a GPU. Redo it only when the PDFs or the chunking change.

### 4. Run: double-click `run.cmd`

It starts three services, each in its own window with its log, waits until they answer and opens **http://127.0.0.1:8000**:

| Service | Port | Window title |
| --- | --- | --- |
| Main app (web interface, orchestrator, legal and grants agents) | 8000 | Main app |
| Fraud detection service | 8100 | Fraud service |
| Business-plan service | 8104 | Business-plan service |

The first question after a start takes about a minute longer: the search models load. **Stop everything with `stop.cmd`** (or close the three windows).

`run.cmd -WithN8n` also starts n8n (Docker Desktop must be running), see [n8n](#n8n-automation).

## Using the app

| Tab | What to do there | Try |
| --- | --- | --- |
| **Chat** (default) | Any question: the planner sends it to the right agents (legal, grants, business plan, fraud) and composes one cited answer. Sources (document, article, page) and the trace of every step are under the answer. | `Quel est le capital minimum d'une société anonyme ?` · `ما هي شروط الحصول على علامة المؤسسة الناشئة؟` · `Je crée une entreprise industrielle à Sfax, besoin de 300 000 DT. Quel programme me convient ?` |
| **Legal workspace** | Legal guidance with your founder profile and documents, sourced action lists, and **contract drafting** (10 agreement types, Word download). | Contract drafting: NDA, two parties, mutual |
| **Aid and financing** | Funding eligibility from a profile form: programmes that may fit, documents usually requested, figures to confirm, why others do not fit. | stage Creation, sector technology, 50 000 TND |
| **Business plan** | Upload a plan for a review report, or build one through a guided chat. | |
| **Fraud review** | Still the original placeholder form (file fingerprint only). **Fraud scoring works in the Chat tab**: describe the payment or attach the invoice. | `Un investisseur me demande 2 000 DT de frais avant de débloquer 500 000 DT, c'est suspect ?` |

The API is documented at http://127.0.0.1:8000/docs.

## What runs where

```
Browser -- http://127.0.0.1:8000 --> Main app (.venv, backend/)
                                       |- planner -> agents in parallel -> verifier -> composer (LangGraph)
                                       |- legal and grants agents, RAG over law/ and grants_and_financial_aids/
                                       |- Groq (main models) / Gemini (fallback, vision OCR) -- internet
                                       |-> Fraud service          :8100 (.venv-fraud, fraud_detection/)
                                       '-> Business-plan service  :8104 (.venv-bp, services/bp/) -- Groq
n8n (Docker) :5678 -- host.docker.internal --> the three services above
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `install.cmd` says a Python version is missing | Install Python 3.12 (tick **Add python.exe to PATH**), open a new terminal, run `install.cmd` again. |
| Answers are lists of passages instead of written answers | No Groq/Gemini key in `.env`, or the free limit is used up. Check http://127.0.0.1:8000/api/health/llm (each provider's status, never the key). |
| Every answer is empty or "not found" | No search index: see step 3. |
| A service window shows an error | Read its last lines; `run.cmd` again restarts only what is not running. |
| Questions sent back to back are slow or fall back to Gemini | Groq's free tier allows 8,000 tokens per minute per model: leave about a minute between complex questions. |
| Search becomes keyword-only after an evaluation | Only one program can use `data/qdrant/` at a time: `stop.cmd` before rebuilding the index or running an evaluation. |
| The business-plan service is slow | It must run with `BP_VECTOR_STORE=off` (run.cmd sets it). `start.bat` in the repo is the service author's local-Ollama launcher, not used here. |
| Accented text sent with `curl` in Git Bash gives HTTP 400 | Use the web page, `/docs` or PowerShell. |

## Manual setup (Mac / Linux, or without the scripts)

```bash
python3.12 -m venv .venv        && .venv/bin/pip install -r requirements.txt
python3.12 -m venv .venv-fraud  && .venv-fraud/bin/pip install -r requirements-fraud.txt
python3.12 -m venv .venv-bp     && .venv-bp/bin/pip install -r services/bp/requirements-dev.txt
cp .env.example .env            # then put your GROQ_API_KEY and GEMINI_API_KEY in it
(cd backend && ../.venv/bin/python -m app.modules.rag.ingestion.pipeline --strategy structural)   # index, once
```

Then one terminal per service (on Windows, `.venv\Scripts\python` instead of `.venv/bin/python`):

```bash
(cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000)
.venv-fraud/bin/python -m fraud_detection serve --port 8100
cd services/bp && LLM_BASE_URL=https://api.groq.com/openai/v1 LLM_API_KEY=<your GROQ_API_KEY> \
  LLM_MODEL_MAIN=qwen/qwen3.8-27b LLM_MODEL_FAST=qwen/qwen3.8-27b \
  BP_LLM_STEPS=parser,reviewer,assessment,critic,drafts,plan_writer,final_writer \
  BP_TIMEOUT_S=170 BP_VECTOR_STORE=off UPLOADS_DIR=../../data/uploads \
  ../../.venv-bp/bin/python -m uvicorn app.main:app --port 8104
```

Tests: `cd backend && ../.venv/bin/python -m pytest` (124 tests, no key, GPU or index needed).

## Legal guidance and contract drafting

The `legal` agent (Meher's work, `backend/app/agents/legal_guidance/` and `contract_drafting/`) answers Tunisian business-law and intellectual-property questions with quote checks, and drafts ten kinds of agreements (NDA, founders, shareholders, investment, services, IP licence…) as editable DOCX after collecting and validating the required terms.

- Workspace: the **Legal workspace** tab of http://127.0.0.1:8000 (`/legal.html` redirects there)
- API: `/api/legal/...` (see http://127.0.0.1:8000/docs)
- Docs: [docs/LEGAL_WORKSPACE.md](docs/LEGAL_WORKSPACE.md), [docs/LEGAL_ARCHITECTURE.md](docs/LEGAL_ARCHITECTURE.md), [docs/LEGAL_DEMO.md](docs/LEGAL_DEMO.md), [docs/LEGAL_VALIDATION.md](docs/LEGAL_VALIDATION.md), [LOCAL_SETUP.md](LOCAL_SETUP.md)
- A local model is supported but off by default (`LOCAL_LLM_ENABLED=false`); the app uses Groq, then Gemini.

## Fraud detection service

The `fraud` agent calls a separate service (`fraud_detection/`), which scores payments and invoices with rules, LightGBM, anomaly detection, graph patterns and sanctions screening, and checks the stamp and signature on an uploaded invoice. Its `risk_score` (0 to 100) is an evidence score, not a probability of fraud. Contract-fairness review is not part of it.

It runs in its own environment (`.venv-fraud`, Python 3.11+: its models were saved with scikit-learn 1.9.1); `install.cmd` and `run.cmd` handle it. Check it at http://127.0.0.1:8100/health. Port 8100 is used because the main app is on 8000. Without the service, fraud questions answer that it is not running. Reading the words on a stamp also needs the Tesseract program (French and English packs).

## Business plan service

The `business_plan` agent sends an uploaded plan (PDF, Word, Excel) to a separate service (`services/bp/`): section completeness, financial checks against Tunisian parameters and sector benchmarks, credibility flags and a Word review report. The **Business plan** tab of the web page also builds a plan step by step with its guided questionnaire.

It runs in its own environment (`.venv-bp`, Python 3.12+); `run.cmd` starts it with Groq and the settings below (the manual setup lists the exact variables). Check it at http://127.0.0.1:8104/health (`llm_reachable` should be `true`). Vision (reading charts in uploaded plans) is left out of `BP_LLM_STEPS` because Groq's free tier has no vision model. The service's own `.env.example` model names (Llama 3.x) and `start.bat` (Ollama) do not work with a new free Groq key; `run.cmd` uses models a free Groq key allows, `BP_TIMEOUT_S=170` and `BP_VECTOR_STORE=off`. With `BP_LLM=off` it runs with rules only. Docs: [services/bp/README.md](services/bp/README.md), [CHANGES_BP.md](CHANGES_BP.md).

Docs: [fraud_detection/README.md](fraud_detection/README.md), [docs/FRAUD_AGENT_API.md](docs/FRAUD_AGENT_API.md), [docs/FRAUD_AGENT_HANDOFF.md](docs/FRAUD_AGENT_HANDOFF.md).

## Grants and financing

The `grants` agent (majdi's rules engine, `backend/app/modules/aid/`, plus our RAG) has two paths:

- **Eligibility** ("which programme fits me?", or a message giving stage, sector, amount, region…): the profile is extracted, a deterministic rules engine matches it against the catalogue (`catalog.yaml`, 10 programmes), and the answer lists matched programmes, excluded ones with reasons and indicative document lists. Each programme cites the indexed page its catalogue entry is based on. No LLM decides eligibility or writes a figure.
- **General questions** ("what does SOTUGAR guarantee?"): answered by the RAG agent over the grants corpus, with verified citations.

Catalogue figures that are not stated in their cited source (BFPME and SOTUGAR investment ranges, the BTS 150,000 TND cap, the AIR headcount) are kept under `unverified`: the rules engine ignores them and answers show them as "to confirm with the provider". The regional-premium zones follow Annexe 2 of décret 2017-389 (pages 16-19), where zones are delegations. Details: [docs/AID_REPORT.md](docs/AID_REPORT.md).

## Evaluations

From `backend/`, with the server stopped:

```powershell
python -m app.eval.retrieval_eval --check                                      # gold answers exist in the corpus
python -m app.eval.retrieval_eval --configs structural:hybrid+rerank@e5-base   # -> docs/RETRIEVAL_EVAL.md
python -m app.eval.routing_eval --dataset heldout --pause 20                   # -> docs/ROUTING_EVAL_HELDOUT.md (~10 min)
python -m app.prompts.library                                                  # -> docs/PROMPT_LIBRARY.md
```

## n8n (automation)

n8n runs in Docker; the app and its two services stay on Windows (GPU, separate Python environments) and n8n reaches them through `host.docker.internal`. Start Docker Desktop, then `run.cmd -WithN8n` (stop with `stop.cmd -WithN8n`), or by hand once the app runs:

```powershell
docker compose -f docker-compose.n8n.yml up -d     # stop with: docker compose -f docker-compose.n8n.yml down
```

Open http://localhost:5678 (first time: create a local owner account), then **Import from File** each workflow from `n8n/` and switch it to **Active**:

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `founder_chat_webhook.json` | POST `{"question": "...", "session_id": "..."}` to http://localhost:5678/webhook/founder-chat | Sends the question to `/api/chat`, returns the answer, sources, agents used and verification. |
| `founder_intake_form.json` | Public form at http://localhost:5678/form/founder-intake | Founder describes the project (stage, sector, need, amount, governorate, language). Calls `/api/aid/match` and `/api/chat` in parallel and shows one report (legal requirements with sources, funding programmes that may fit). Saves a JSON record in `data/n8n/intake/`. |
| `daily_health_check.json` | Every day at 08:00 (Africa/Tunis), or on demand | Checks the app, the fraud and business-plan services, and the Groq/Gemini keys and models (`/api/health/llm`, no tokens used). Saves a status in `data/n8n/health/`; if something is down the run ends in error (red in the executions list). |

Run the health check now: `docker exec law_rag-n8n-1 n8n execute --id=<workflow id>` (ids: `docker exec law_rag-n8n-1 n8n list:workflow`).

The JavaScript of the Code nodes is in `n8n/src/*.js`; after editing it, rebuild the JSON with `python n8n/src/build_workflows.py` and import again.

## Layout

```
backend/app/orchestrator/   planner, LangGraph graph, verifier, composer, guardrail, sessions
backend/app/agents/         agent base class, RAG agent, registry (plug your agent in here)
backend/app/prompts/        versioned prompt library (YAML) and loader
backend/app/modules/rag/    ingestion (extract, chunk, index) and retrieval (BM25, dense, hybrid, rerank)
backend/app/modules/intake/ uploads to text, vision OCR
backend/app/services/       LLM (Groq / Gemini), embeddings, Qdrant
backend/app/eval/           retrieval and routing evaluations with their datasets
backend/tests/              tests (124)
scripts/                    install.ps1, run.ps1, stop.ps1 (used by install.cmd, run.cmd, stop.cmd)
frontend/                   web interface
n8n/                        exported workflows
docs/                       architecture, evaluations, prompt library
data/                       generated, git-ignored: chunks, vectors, models, cache, OCR, sessions
```
