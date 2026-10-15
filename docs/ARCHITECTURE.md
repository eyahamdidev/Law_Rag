# Architecture

One FastAPI app serves the web shell and three workspaces. A router decides which workspace a question belongs to. Legal questions then go to domain workers. Fraud and aid do not pass through the legal workers.

```
browser
  → FastAPI
      → intake (language, later OCR)
      → router
          → cited answers: retrieve → domain worker → generate → verifier → composer
          → fraud review: hash and planned signals
          → aid: stage filter on the local catalog
```

The deck's stack stays the target for cited answers: LangGraph for the bounded workflow, Ollama for the local model and vision, bge-m3 for embeddings, Qdrant for vectors, MLflow for traces. n8n, if added later, only triggers the API. Client stubs live in `backend/app/services/` and raise `NotImplementedError` until a module calls them.

## Modules you can replace

| Path | Contract |
| --- | --- |
| `modules/router/domain_router.py` | `route_query(question) -> intent, domains` |
| `modules/rag/ingestion/pipeline.py` | Read PDFs into the metadata fields listed in `metadata.py` |
| `modules/rag/retrieval/hybrid.py` | `retrieve(question, domains) -> passages` |
| `modules/domains/*.py` | `draft(question) -> claims` for legal, tax, banking, labour, IP |
| `modules/fraud/detector.py` | `analyze_upload(...) -> risk_level, signals` |
| `modules/aid/matcher.py` | `match(profile) -> programs` |
| `modules/verifier/` | Citation existence, claim support, abstention |
| `modules/composer/answer.py` | Final text. Abstain when there is no passage |
| `graph/workflow.py` | The function LangGraph should replace |

`GET /api/modules` returns this map. `GET /api/corpus` counts files under `law/`, `grants_and_financial_aids/`, and `fraud_detection/`.

## Cited answers

Answers name the code, article, and version date once retrieval exists. Until then the composer abstains and says so. A retrieval score is relevance, not the probability that the answer is legally correct. Unknown dates stay unknown. Publication date and effective date are different fields.

Domain workers share one local model. A worker may later request one extra search. The verifier stays deterministic for document id, page, and article, with a separate claim-support check.

## Fraud review

This workspace was not in the deck. It reviews a file the founder uploads: invoice, bank statement, financing application, or business plan. Planned signals are missing fiscal identifiers, inconsistent dates, duplicate hashes, and totals that do not match the lines. They are reasons for a person to look again. The module does not declare that a document is legally fraudulent.

Uploads are hashed in the response and discarded. Put future labelled samples in `fraud_detection/`. Starter rows for evaluation are in `backend/app/eval/datasets/fraud_labels.jsonl`.

## Aid and financing

This workspace was not in the deck. It lists programs whose files are already in the repo:

- BFPME creation and extension checklists, plus the 2024 financing form
- Business-plan models, including the GIZ model
- Startup Act texts under `law/.../01_STARTUPS`
- Investment-law texts under `law/.../02_INVESTMENT`

The matcher filters on company stage only. Sector and need are stored on the request and are not rules yet. Questions about what a law says still belong to cited answers.

## Business plan

Separate service in `services/bp/` (port 8104). The gateway talks to it over HTTP with `file_ref` uploads (`data/uploads/<sha256>`), never by import. Two input methods, usable together: upload a plan, or answer the guided questionnaire. The gateway also keeps a per-session profile (header `X-Session-Id`) filled from chat and the aid tab; it is sent as `profile`. The service merges questionnaire, profile and plan, reports conflicts, and checks every figure in plain Python. Routes: `POST /api/bp/questionnaire`, `POST /api/bp/run`, `GET /api/files/{sha256}`, `GET|PUT /api/profile`. See `services/bp/README.md`.

## Evaluation hypotheses

From the deck, to be calibrated after a dense-only baseline:

- Recall@5 and MRR on 50 questions
- Citation validity near 100 percent, tracked separately from claim support
- Routing Macro-F1 at least 0.90 on about 60 labelled queries
- Refusal at least 85 percent and false refusal at most 10 percent
- Field-level F1 on about 15 uploaded documents, set after the first run
- Latency p50 / p95 tracked beside quality, not instead of it

Constants live in `backend/app/eval/metrics.py`.