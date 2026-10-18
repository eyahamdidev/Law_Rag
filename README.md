# Tunisian Legal & Financial Assistant

Multi-agent assistant for Tunisian founders. A LangGraph orchestrator plans which agents to call (legal, grants, business plan, marketing, contract review), runs them in parallel over a cited RAG index of Tunisian official texts and funding programmes, verifies every citation and claim, and composes one answer in French, Arabic or English. Uploaded PDFs, scans and photos are read with text extraction and vision OCR. n8n connects it to a webhook or Telegram.

- How it works, and how to plug in your agent: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Results: [docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md), [docs/ROUTING_EVAL_HELDOUT.md](docs/ROUTING_EVAL_HELDOUT.md), [docs/ROUTING_EVAL.md](docs/ROUTING_EVAL.md), [docs/ROUTING_EVAL_PLANNER_V3.md](docs/ROUTING_EVAL_PLANNER_V3.md)
- Prompts and their iterations: [docs/PROMPT_LIBRARY.md](docs/PROMPT_LIBRARY.md)

## Setup for teammates (first time, about 1 hour on a CPU laptop)

Some things are deliberately not on GitHub, so every new clone sets them up once:

| Not in the repository | Why | What you do |
| --- | --- | --- |
| `.env` | holds API keys, which must never be pushed | create your own from `.env.example` (step 3) |
| `.venv/` | installed packages, specific to each machine | `pip install` (step 2) |
| `data/` | generated index, vectors and models, several GB | build it (step 4), or get a copy (step 4b) |

### 0. Prerequisites

- **Git** and **Git LFS** (https://git-lfs.com). One large law PDF is stored with LFS; without it that document is silently skipped.
- **Python 3.10 or newer**: `python --version`
- About **4 GB** of free disk space and an internet connection for the first model download.

### 1. Clone the repository

```powershell
git lfs install
git clone https://github.com/eyahamdidev/Law_Rag.git
cd Law_Rag
git checkout feat/orchestrator-rag
```

### 2. Create the environment and install packages

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Mac / Linux: `python3 -m venv .venv`, then `source .venv/bin/activate`, then the same `pip install`.

Activate the environment again (`.venv\Scripts\activate`) each time you open a new terminal.

### 3. Add your own API keys

```powershell
copy .env.example .env
notepad .env
```

Mac / Linux: `cp .env.example .env`, then edit it.

Fill in two lines with **your own** free keys (do not share keys: the free limits are per account):

```
GROQ_API_KEY=gsk_...       # https://console.groq.com/keys
GEMINI_API_KEY=...         # https://aistudio.google.com/apikey
```

Without keys the app still starts: the planner falls back to keywords and answers list the most relevant passages instead of a written answer.

### 4. Build the search index (once)

```powershell
cd backend
python -m app.modules.rag.ingestion.pipeline --strategy structural
```

This reads the PDFs in `law/` and `grants_and_financial_aids/`, splits them into about 7,000 passages, downloads the embedding model (about 1.1 GB, first time only) and embeds every passage. It takes about **60 minutes on a CPU**, about 10 on an NVIDIA GPU (step 6). It is cached in `data/`; you only do it again when the corpus or the chunking changes.

### 4b. Or skip the build with a copy

Ask a teammate who has built it for a zip of their `data/index/` and `data/qdrant/` folders (about 270 MB) and unzip both into your `Law_Rag\data\`. Copy the whole `qdrant` folder, not a single collection inside it. Then skip step 4.

### 5. Run the app

```powershell
cd backend          # if you are not there already
uvicorn app.main:app --reload
```

Wait for `Application startup complete`, then **about one more minute** while the search models load (the first launch also downloads the reranker, about 1.1 GB). Open:

- **http://127.0.0.1:8000**: the web interface. Ask for example `Quel est le capital minimum pour une SARL ?`, `ما هي شروط الحصول على علامة المؤسسة الناشئة؟` or `I'm launching a fintech: which legal form and what funding?`. Under each answer you see the sources (document, article, page) and the trace of every step.
- **http://127.0.0.1:8000/docs**: call the API by hand (`/api/chat`, `/api/search`, `/api/agents`).

The **Aid and financing** tab is also available in the main web interface. It
calls `/api/aid/match` and displays eligible programmes, excluded programmes
with reasons, source pages, required documents, legal handoffs, and the full
deterministic rule trace. You can provide either structured profile fields or a
founder description; missing stage, sector, and need fields are extracted from
the description when possible.

Stop with Ctrl+C.

### 6. Optional: use an NVIDIA GPU (Windows)

```powershell
pip uninstall -y onnxruntime
pip install --no-deps onnxruntime-directml
```

Then add `EMBEDDING_DEVICE=dml` to `.env`. On laptops with Intel + NVIDIA graphics the NVIDIA card is usually device 1 (the default); if nothing gets faster, try `EMBEDDING_DEVICE_ID=0`. Without a GPU everything still works on the CPU.

### 7. Check that everything works

```powershell
cd backend
pytest
```

17 tests, about 5 seconds. They need no API key, no GPU and no index.

## Good to know

- **Leave about a minute between complex questions.** Groq's free tier allows 8,000 tokens per minute per model; questions sent back to back can fall back to Gemini or come back empty.
- **Only one program can use `data/qdrant/` at a time.** Stop the server before rebuilding the index or running an evaluation, or search falls back to keywords only.
- **In Git Bash**, accented text sent with `curl` can arrive mis-encoded (HTTP 400). Use the web page, `/docs` or PowerShell.
- **Agents not built yet** (business plan, marketing, fraud) answer "not connected yet". To plug yours in, follow "The agent contract" in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Legal guidance and contract drafting

The `legal` agent (Meher's work, `backend/app/agents/legal_guidance/` and `contract_drafting/`) answers Tunisian business-law and intellectual-property questions with quote checks, and drafts ten kinds of agreements (NDA, founders, shareholders, investment, services, IP licence…) as editable DOCX after collecting and validating the required terms.

- Workspace: the **Legal workspace** tab of http://127.0.0.1:8000 (`/legal.html` redirects there)
- API: `/api/legal/...` (see http://127.0.0.1:8000/docs)
- Docs: [docs/LEGAL_WORKSPACE.md](docs/LEGAL_WORKSPACE.md), [docs/LEGAL_ARCHITECTURE.md](docs/LEGAL_ARCHITECTURE.md), [docs/LEGAL_DEMO.md](docs/LEGAL_DEMO.md), [docs/LEGAL_VALIDATION.md](docs/LEGAL_VALIDATION.md), [LOCAL_SETUP.md](LOCAL_SETUP.md)
- A local model is supported but off by default (`LOCAL_LLM_ENABLED=false`); the app uses Groq, then Gemini.

## Fraud detection service

The `fraud` agent calls a separate service (`fraud_detection/`), which scores payments and invoices with rules, LightGBM, anomaly detection, graph patterns and sanctions screening, and checks the stamp and signature on an uploaded invoice. Its `risk_score` (0 to 100) is an evidence score, not a probability of fraud. Contract-fairness review is not part of it.

It needs **Python 3.11 or newer in its own environment**: its models were saved with scikit-learn 1.9.1, which does not install on the main app's Python 3.10. Once:

```powershell
cd D:\Law_Rag
py -3.11 -m venv .venv-fraud
.venv-fraud\Scripts\python -m pip install "scikit-learn==1.9.1" lightgbm numpy pandas scipy joblib fastapi uvicorn pydantic httpx pillow pymupdf pytesseract
```

Then, in a second terminal, before asking fraud questions:

```powershell
cd D:\Law_Rag
.venv-fraud\Scripts\python -m fraud_detection serve --port 8100
```

Check it at http://127.0.0.1:8100/health. Port 8100 is used because the main app is on 8000. Without the service, fraud questions answer that it is not running. Reading the words on a stamp also needs the Tesseract program (French and English packs).

## Business plan service

The `business_plan` agent sends an uploaded plan (PDF, Word, Excel) to a separate service (`services/bp/`): section completeness, financial checks against Tunisian parameters and sector benchmarks, credibility flags and a Word review report. The **Business plan** tab of the web page also builds a plan step by step with its guided questionnaire.

It needs **Python 3.12 or newer in its own environment** (`services/bp/requirements.lock` pins numpy 2.5.3). Once:

```powershell
cd D:\Law_Rag
py -3.13 -m venv .venv-bp
.venv-bp\Scripts\python -m pip install -r services\bp\requirements-dev.txt
```

Then, in a third terminal (PowerShell), with your Groq key:

```powershell
cd D:\Law_Rag\services\bp
$env:LLM_BASE_URL = "https://api.groq.com/openai/v1"
$env:LLM_API_KEY = "<your GROQ_API_KEY>"
$env:LLM_MODEL_MAIN = "qwen/qwen3.8-27b"; $env:LLM_MODEL_FAST = "qwen/qwen3.8-27b"
$env:BP_LLM_STEPS = "parser,reviewer,assessment,critic,drafts,plan_writer,final_writer"
$env:UPLOADS_DIR = "D:\Law_Rag\data\uploads"
..\..\.venv-bp\Scripts\python -m uvicorn app.main:app --port 8104
```

Check it at http://127.0.0.1:8104/health (`llm_reachable` should be `true`). Vision (reading charts in uploaded plans) is left out of `BP_LLM_STEPS` because Groq's free tier has no vision model. The service's own `.env.example` model names (Llama 3.x) and `start.bat` (Ollama) do not work with a new free Groq key; use the values above. With `BP_LLM=off` it runs with rules only. Docs: [services/bp/README.md](services/bp/README.md), [CHANGES_BP.md](CHANGES_BP.md).

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

Needs Docker Desktop: `docker compose up --build api n8n`, open http://localhost:5678 and import a workflow from `n8n/`:

- `founder_chat_webhook.json`: POST `{"question": "...", "session_id": "..."}` to `/webhook/founder-chat`.
- `founder_chat_telegram.json`: Telegram bot; text goes to `/api/chat`, documents and photos to `/api/chat/upload`.

These workflows have not been run in n8n yet.

## Layout

```
backend/app/orchestrator/   planner, LangGraph graph, verifier, composer, guardrail, sessions
backend/app/agents/         agent base class, RAG agent, registry (plug your agent in here)
backend/app/prompts/        versioned prompt library (YAML) and loader
backend/app/modules/rag/    ingestion (extract, chunk, index) and retrieval (BM25, dense, hybrid, rerank)
backend/app/modules/intake/ uploads to text, vision OCR
backend/app/services/       LLM (Groq / Gemini), embeddings, Qdrant
backend/app/eval/           retrieval and routing evaluations with their datasets
backend/tests/              contract tests
frontend/                   web interface
n8n/                        exported workflows
docs/                       architecture, evaluations, prompt library
data/                       generated, git-ignored: chunks, vectors, models, cache, OCR, sessions
```
