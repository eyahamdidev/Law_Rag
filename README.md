# Tunisian Legal & Financial Assistant

An assistant for people starting a business in Tunisia. You ask a question in French, Arabic or English, and it answers from the official texts (laws, decrees, funding programme documents), with the source of every statement: document, article and page.

Behind the chat there are four specialised agents:

- **Legal**: company law, intellectual property, contract drafting.
- **Grants and financing**: which funding programmes fit your project, and why others do not.
- **Business plan**: reviews an uploaded plan, or helps you write one.
- **Fraud**: checks a payment request or an invoice for warning signs.

A planner decides which agents a question needs and runs them in parallel. A verifier then checks that each citation exists and really supports what is said, and the final answer is written in the language of the question. You can also upload PDFs, scans and photos. n8n adds three automations around the app: a chat webhook, a founder intake form and a daily health check.

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (how it works), [docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md) and [docs/ROUTING_EVAL_HELDOUT.md](docs/ROUTING_EVAL_HELDOUT.md) (evaluation results), [docs/PROMPT_LIBRARY.md](docs/PROMPT_LIBRARY.md) (prompts and their versions).

---

## Installing and running it (Windows)

The whole setup is done by two scripts. Count about 20 minutes the first time, plus the search index (step 4).

### Step 1. Install these first

| What | Why | Download |
| --- | --- | --- |
| **Git** and **Git LFS** | to download the code; one large PDF is stored with Git LFS | https://git-scm.com and https://git-lfs.com |
| **Python 3.12**, 64-bit | runs the app | https://www.python.org/downloads/ (during the installation, tick **"Add python.exe to PATH"**) |
| A **Groq** API key and a **Gemini** API key | the language models. Both are free and take about two minutes to create | Groq: https://console.groq.com/keys, Gemini: https://aistudio.google.com/apikey |
| About **8 GB** of free disk space | Python packages, models (2.2 GB, downloaded once) and the index | |
| *Optional:* **Docker Desktop** | only needed for the n8n workflows | https://www.docker.com/products/docker-desktop/ |
| *Optional:* **Tesseract OCR** (French and English) | only used to read the text on invoice stamps | https://github.com/UB-Mannheim/tesseract/wiki |

### Step 2. Download the code

Open PowerShell in the folder where you want the project, then type:

```powershell
git lfs install
git clone --branch integration/agents https://github.com/eyahamdidev/Law_Rag.git
cd Law_Rag
```

### Step 3. Run the installer

Double-click **`install.cmd`** in the `Law_Rag` folder.

Or, in PowerShell inside the `Law_Rag` folder, type:

```powershell
.\install.cmd
```

The `.\` at the start is needed in PowerShell. Without it, PowerShell may run another program with the same name.

The installer does the following. Just answer its questions:

1. It checks that the law PDFs were downloaded.
2. It creates three Python environments, one per service, because they need different library versions.
3. It asks for your **Groq** and **Gemini** keys and saves them in a local `.env` file. That file is never uploaded to GitHub.
4. It offers to build the search index (see step 4).
5. It runs the tests: 124 tests, about 30 seconds.

You can run it again at any time. It updates what is there and keeps your keys.

If your PC has an NVIDIA graphics card, `.\install.cmd -Gpu` makes the search faster.

### Step 4. The search index (only once)

The app searches an index built from the PDFs. The index is too large for GitHub, so you need to get it one of two ways:

- **Download it**, if a link to the ready-made index was given to you. Unzip it so that you get the folders `Law_Rag\data\index` and `Law_Rag\data\qdrant`.
- **Or build it**: answer `y` when the installer asks, or run `.\install.cmd -BuildIndex`. It takes about **1 hour on a normal PC** (about 10 minutes with a GPU). You only do it once.

### Step 5. Start the app

Double-click **`run.cmd`**, or type `.\run.cmd` in PowerShell.

Three windows open, one per service. When everything is ready, the browser opens **http://127.0.0.1:8000** on its own.

| Service | Address |
| --- | --- |
| Main app (web page, orchestrator, legal and grants agents) | http://127.0.0.1:8000 |
| Fraud detection service | http://127.0.0.1:8100 |
| Business plan service | http://127.0.0.1:8104 |

The **first question takes about a minute longer** than the others, because the search models load then.

To stop everything, double-click **`stop.cmd`**, or close the three windows.

---

## Trying it out

| Tab | What it does | Something to try |
| --- | --- | --- |
| **Chat** (opens first) | Ask anything. The answer lists its sources, and you can open the steps the system went through. | `Quel est le capital minimum d'une société anonyme ?` <br> `ما هي شروط الحصول على علامة المؤسسة الناشئة؟` <br> `Je crée une entreprise industrielle à Sfax, besoin de 300 000 DT. Quel programme me convient ?` |
| **Legal workspace** | Legal guidance based on your profile and documents, and drafting of 10 kinds of contracts (downloadable as Word). | Draft a mutual NDA between two parties |
| **Aid and financing** | Fill in your profile to see the funding programmes that may fit, the documents usually asked for, and why the others do not fit. | Stage "Creation", sector "technology", 50 000 TND |
| **Business plan** | Upload a plan to get a review, or build one by answering guided questions. | |
| **Fraud review** | The full fraud check works from the **Chat** tab: describe the payment or attach the invoice. | `Un investisseur me demande 2 000 DT de frais avant de débloquer 500 000 DT, c'est suspect ?` |

The API documentation is at http://127.0.0.1:8000/docs.

---

## n8n workflows (optional)

n8n runs in Docker and calls the app, so start the app first.

1. Start **Docker Desktop** and wait until it says it is running.
2. Start the app together with n8n:
   ```powershell
   .\run.cmd -WithN8n
   ```
   If the app is already running, you can start only n8n with `docker compose -f docker-compose.n8n.yml up -d`.
3. Open **http://localhost:5678**. The first time, n8n asks you to create a local account.
4. For each file in the `n8n/` folder, choose **Import from File**, then switch the workflow to **Active**.

| File | How it starts | What it does |
| --- | --- | --- |
| `founder_chat_webhook.json` | A POST request to http://localhost:5678/webhook/founder-chat with `{"question": "...", "session_id": "..."}` | Sends the question to the assistant and returns the answer with its sources. |
| `founder_intake_form.json` | A form at http://localhost:5678/form/founder-intake | The founder describes the project. The workflow asks for the matching funding programmes and the legal requirements at the same time, then shows one report. It also saves a copy in `data/n8n/intake/`. |
| `daily_health_check.json` | Every day at 08:00 (Tunis time), or by hand | Checks that the three services and the Groq/Gemini keys work, without spending tokens. It saves the result in `data/n8n/health/`, and the run turns red if something is down. |

To stop: `.\stop.cmd -WithN8n`.

---

## If something goes wrong

| Problem | What to do |
| --- | --- |
| The installer says a Python version is missing | Install Python 3.12 with **"Add python.exe to PATH"** ticked, open a **new** PowerShell window, and run `.\install.cmd` again. |
| Typing `run.cmd` gives an error about a path that is not your `Law_Rag` folder | Type `.\run.cmd` (with `.\`), or double-click the file. |
| Answers are lists of raw passages instead of real answers | The Groq/Gemini keys are missing or their free limit is used up. Open http://127.0.0.1:8000/api/health/llm to see the status of each provider. The page never shows the keys. To change a key, edit `.env` and restart with `.\stop.cmd` then `.\run.cmd`. |
| Every answer says nothing was found | The search index is missing: see step 4. |
| One of the three windows shows an error | Read its last lines. Running `.\run.cmd` again restarts only what stopped. |
| Questions asked quickly one after another are slow | Groq's free plan limits how many words per minute each model can process. Wait about a minute between long questions. |
| The first question is slow | That is normal: the models are loading. The next ones are faster. |

---

## Mac / Linux, or setting up without the scripts

```bash
python3.12 -m venv .venv        && .venv/bin/pip install -r requirements.txt
python3.12 -m venv .venv-fraud  && .venv-fraud/bin/pip install -r requirements-fraud.txt
python3.12 -m venv .venv-bp     && .venv-bp/bin/pip install -r services/bp/requirements-dev.txt
cp .env.example .env            # then put your keys in GROQ_API_KEY and GEMINI_API_KEY
(cd backend && ../.venv/bin/python -m app.modules.rag.ingestion.pipeline --strategy structural)   # index, once
```

Then start each service in its own terminal:

```bash
(cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000)
.venv-fraud/bin/python -m fraud_detection serve --port 8100
cd services/bp && LLM_BASE_URL=https://api.groq.com/openai/v1 LLM_API_KEY=<your Groq key> \
  LLM_MODEL_MAIN=qwen/qwen3.8-27b LLM_MODEL_FAST=qwen/qwen3.8-27b \
  BP_LLM_STEPS=parser,reviewer,assessment,critic,drafts,plan_writer,final_writer \
  BP_TIMEOUT_S=170 BP_VECTOR_STORE=off UPLOADS_DIR=../../data/uploads \
  ../../.venv-bp/bin/python -m uvicorn app.main:app --port 8104
```

To run the tests: `cd backend && ../.venv/bin/python -m pytest`. No key, GPU or index is needed.

---

## How the project is organised

```
backend/app/orchestrator/   planner, LangGraph graph, verifier, composer, guardrails
backend/app/agents/         the agents and the registry where they are plugged in
backend/app/prompts/        the prompt library (versioned YAML files)
backend/app/modules/rag/    reading and splitting the PDFs, indexing, and search (BM25, vectors, reranker)
backend/app/modules/aid/    grants rules engine and programme catalogue
backend/app/modules/intake/ uploaded files to text, OCR
backend/app/services/       language models (Groq, Gemini), embeddings, vector database
backend/app/eval/           retrieval and routing evaluations
backend/tests/              tests
fraud_detection/            fraud detection service
services/bp/                business plan service
frontend/                   web page
n8n/                        n8n workflows (JSON)
scripts/                    what install.cmd, run.cmd and stop.cmd run
law/, grants_and_financial_aids/   the source PDFs
docs/                       architecture, evaluations, prompt library
```

### A few details per agent

- **Legal** (`backend/app/agents/legal_guidance/`, `contract_drafting/`): answers business-law and IP questions and checks that its quotes really appear in the texts. It drafts ten kinds of agreements (NDA, founders, shareholders, investment, services, IP licence…) as Word files. See [docs/LEGAL_WORKSPACE.md](docs/LEGAL_WORKSPACE.md).
- **Grants** (`backend/app/modules/aid/`): eligibility is decided by fixed rules over a catalogue of 10 programmes, never by the language model. Each programme points to the page of the document it comes from. Figures we could not find in a source are shown as "to confirm with the provider". General questions ("what does SOTUGAR guarantee?") go through the search instead. See [docs/AID_REPORT.md](docs/AID_REPORT.md).
- **Fraud** (`fraud_detection/`): scores a payment or invoice with rules, a LightGBM model, anomaly detection and sanctions screening, and checks the stamp and signature on an invoice. The score (0 to 100) shows how much evidence there is, not a probability. See [fraud_detection/README.md](fraud_detection/README.md).
- **Business plan** (`services/bp/`): checks that the sections are complete, tests the figures against Tunisian benchmarks and produces a Word review. See [services/bp/README.md](services/bp/README.md).

### Re-running the evaluations

From `backend/`, with the app stopped:

```powershell
python -m app.eval.retrieval_eval --configs structural:hybrid+rerank@e5-base   # -> docs/RETRIEVAL_EVAL.md
python -m app.eval.routing_eval --dataset heldout --pause 20                   # -> docs/ROUTING_EVAL_HELDOUT.md (about 10 min)
```
