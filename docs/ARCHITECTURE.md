# Architecture

```
Telegram / webhook / web UI
        │  n8n (n8n/*.json): channel trigger, file download, error replies
        ▼
FastAPI  POST /api/chat  ·  POST /api/chat/upload (files)
        │
        ├─ intake        uploads → text: PDF text, vision OCR for scans and photos
        ▼
LangGraph orchestrator (backend/app/orchestrator/graph.py)
   plan ──► run_agent × N (parallel, LangGraph Send) ──► verify ──► compose
     │                                                              ▲
     └── clarify / out of scope ────────────────────────────────────┘
```

| Step | File | What it does | LLM calls |
| --- | --- | --- | --- |
| plan | `orchestrator/planner.py` | Picks 0–3 agents, writes each a sub-task and a French search query, extracts profile facts, or asks a clarifying question. Keyword router if no LLM or bad JSON. | 1 (fast tier) |
| run_agent | `agents/*.py` | Each agent gets an `AgentRequest`, returns an `AgentResult`. Agents never call each other. | 1–2 per RAG agent |
| verify | `orchestrator/verifier.py` | Citation validity in code (passage exists, page in index). Claim support by LLM, each claim against only its cited passages. | 1 (fast tier) |
| compose | `orchestrator/composer.py` | Global citation numbers, drops unsupported claims, merges agents. Skipped when one agent passed verification. | 0–1 |

A turn with two agents costs at most 1 + 2×2 + 1 + 1 = 7 LLM calls, usually 5.

## Why this shape

- **Router/planner + parallel workers + verifier**, not one big prompt: legal and funding questions need different corpora and filters. Separate agents keep retrieval clean, and each failure shows up in the trace for one step.
- **Not a swarm or agent-to-agent chat**: more calls, more latency, harder to evaluate, and nothing in this use case needs agents to negotiate. Every hand-off goes through the graph state.
- **Not a fixed sequential chain**: most questions need one or two agents, so the planner calls only those, in parallel.
- **One bounded loop**: a RAG agent may run one follow-up search when its draft abstains. That is the agentic decision, and the bound keeps latency predictable.
- **Deterministic where possible**: citation checks, the keyword fallback and eligibility rules are code. The model handles language.

## The agent contract (for teammates)

`backend/app/schemas/agents.py`:

```python
class AgentRequest:   task, search_query, question, language, profile: FounderProfile,
                      attachments: list[Attachment], history: list[Turn]
class AgentResult:    agent, status ("ok" | "abstained" | "needs_info" | "placeholder" | "error"),
                      answer, claims: list[Claim], citations: list[Citation], passages,
                      missing_info: list[str], profile_updates: dict, confidence, trace
```

To plug in your agent:

1. Create `backend/app/agents/<your_agent>.py` with a class extending `app.agents.base.Agent` and a `run(request) -> AgentResult` method.
2. In `backend/app/agents/registry.py`, replace your `PlaceholderAgent(...)` entry with your class. Keep the card `id`. Make `description` and `use_when` accurate, because the planner reads only those.
3. To search the corpus, call `app.modules.rag.retrieval.hybrid.search(query, corpora=[...])` or reuse `RagAgent`. Cite with `[n]` markers that match `citations[].ref`, and put the cited passages in `passages`, or the verifier marks the citations invalid.
4. Put your prompts in `backend/app/prompts/library/<agent>.<name>.yaml` and load them with `get_prompt(...)` (see below).
5. Return `missing_info` instead of guessing facts about the founder, and `profile_updates` for facts you learn (sector, governorate…), so other agents can reuse them.
6. Add your routing examples to `backend/app/eval/datasets/routing_queries.jsonl`.

## RAG

| Choice | Value | Why |
| --- | --- | --- |
| Corpus | `law/` (19 PDFs) + `grants_and_financial_aids/` (84 PDFs), 97 unique documents after hash dedupe | Official texts and programme pages a founder needs. `business_plan/` can be added with `--corpora`. |
| Extraction | PyMuPDF per page, font repair, NFKC, running-header removal | The Companies Code PDF has a shifted font encoding. Arabic extracts as presentation forms. JORT banners repeat on every page. |
| Chunking | `structural`: one chunk per article, long articles split with a context header; recursive paragraph split for non-legal docs. Baseline `fixed`: 1000 chars / 150 overlap | An article is what a citation names. JORT issues carry several texts, so the act (decree number) is tracked per article. |
| Embeddings | multilingual-e5-base (ONNX), cached in SQLite; GPU through DirectML when available, CPU otherwise | French + Arabic, runs without PyTorch or CUDA. e5-base beat e5-small (Recall@5 0.72 vs 0.62 dense); e5-large fits a 4 GB GPU only at batch 4. See `docs/RETRIEVAL_EVAL.md`. |
| Reranker | jina-reranker-v2-base-multilingual on the top 20 | Recall@5 0.68 → 0.82 and MRR 0.49 → 0.74 for ~1.9 s per query on a GTX 1050. |
| Vector store | Qdrant, embedded by default, server in Docker | Payload filters on corpus and domain. Same API in both modes. |
| Retrieval | BM25 + dense, Reciprocal Rank Fusion, optional cross-encoder rerank, max 5 distinct passages | BM25 catches article numbers and exact terms, dense catches paraphrases and cross-language questions. |
| Query side | Planner writes a French query, agents fuse it with the original wording | Most of the corpus is French. English and Arabic questions still need to find it. |

Build the index from `backend/`:

```bash
python -m app.modules.rag.ingestion.pipeline --strategy structural
python -m app.modules.rag.ingestion.pipeline --strategy fixed
python -m app.eval.retrieval_eval
```

Known corpus problems (see `data/index/report.json` after a build):

- 513 pages have no text layer: the 1976 Foreign Exchange Code (64 p.), the BCT exchange-regulation collection (249 p.), the 2016 API procedures manual (199 p.). `python -m app.modules.intake.extractor --corpus-ocr` OCRs them with the vision model, then rebuild the index.
- JORT issue PDFs contain the whole gazette (appointments, land tables), not just the law, which adds noise.
- Some grant "sources" are not useful: an "Access Denied" page (UNDP), a civil-service code of conduct filed under decree 2017-389, German-language GIZ material.
- No labour code, tax code or IP law yet. Questions on those topics should get an abstention, not an answer.

## Prompt library

`backend/app/prompts/library/*.yaml`, one file per prompt, every version kept with its techniques, observed failures and fix. `python -m app.prompts.library` regenerates `docs/PROMPT_LIBRARY.md`. Each trace step names the prompt version it ran (`rag.answer@v1 via groq/llama-3.3-70b-versatile`).

Add a new version when an evaluation or a trace shows a failure. Record the failure on the old version and the change on the new one. That is the before/after the grading asks for.

## Business plan

Separate service in `services/bp/` (port 8104, own Python 3.11 environment). The gateway (`backend/app/api/routes/bp.py`, `modules/bp/client.py`) talks to it over HTTP and shares uploads by reference (`data/uploads/<sha256>`), never by import. Its prompts live in `services/bp/prompts/`. See `CHANGES_BP.md`.

## Evaluation

| What | Command | Output |
| --- | --- | --- |
| Retrieval: chunking × mode × model, Recall@1/5, MRR, per language, latency | `python -m app.eval.retrieval_eval` | `docs/RETRIEVAL_EVAL.md` |
| Routing: keyword vs LLM planner, Macro-F1 per agent | `python -m app.eval.routing_eval` | `docs/ROUTING_EVAL.md` |
| Contracts and offline behaviour | `pytest backend` | |

The question sets were written by the orchestrator owner from real passages. Teammates should review them and add their own before the final report.
