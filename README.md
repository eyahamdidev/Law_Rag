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
