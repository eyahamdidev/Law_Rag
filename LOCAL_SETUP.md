# Local setup — Windows, Python 3.12 x64

Open the tracked `Legal-Agent.code-workspace` in VS Code. Select `.venv/Scripts/python.exe`. Active feature checkout: `legal-guidance`. The `Legal assistant: run API` task and `Legal assistant: API` debugger start the prepared local model first.

## Fresh installation

```powershell
git lfs install
git clone -c core.longpaths=true --branch legal-guidance https://github.com/eyahamdidev/Law_Rag.git
cd Law_Rag
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-legal.lock.txt
Copy-Item .env.example .env
```

Do not overwrite an existing `.env`. The direct dependencies are in `requirements-legal.txt`; the lock records this laptop's environment. No execution-policy change is needed.

## Local resources and documents

```powershell
.\.venv\Scripts\python.exe scripts\prepare_local_runtime.py
.\.venv\Scripts\python.exe -m pip install data\downloads\tesserocr-2.11.0-cp312-cp312-win_amd64.whl
.\.venv\Scripts\python.exe scripts\prepare_embeddings.py
.\.venv\Scripts\python.exe scripts\configure_local_mode.py
.\.venv\Scripts\python.exe scripts\import_legal_sources.py
.\.venv\Scripts\python.exe scripts\ocr_legal_corpus.py
```

The public corpus includes eight WIPO legislation PDFs and provenance sidecars: the six supplied texts plus official French patent and trademark versions. The latter can be regenerated with `scripts/fetch_french_ip_sources.py`. The importer copies it to local storage and optionally imports the selected WIPO explanatory guides from Downloads. `--input PATH` changes their location. Unsupplied optional files are recorded in `data/corpus/import-report.json`. Private example contracts remain outside the corpus; use document intake for them.

Ignored `data/` contains quantized Qwen3 1.7B, llama.cpp CPU runtime, multilingual E5-small ONNX weights and Tesseract language data. Downloads record provenance; large models are SHA-256 checked. Preparation needs internet and several GB of disk. OCR and CPU inference take time. These runtime scripts target Windows; other platforms need compatible runtime/OCR installations.

## Index

Stop the API before replacing its index or accessing embedded Qdrant from another process.

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m app.modules.rag.ingestion.pipeline --strategy structural
Pop-Location
.\.venv\Scripts\python.exe scripts\export_legal_corpus.py
```

For text extraction only add `--chunks-only`; embed existing chunks with `--reuse-chunks`. After successful vector indexing set `RETRIEVAL_MODE=hybrid` in `.env`. Reranking is optional and disabled locally. OCR gaps are recorded in `data/index/report.json`; unreadable pages are excluded from evidence. CSV exports go to `data/exports/`.

## Run

```powershell
.\run-agent.cmd
```

This starts the local model on 127.0.0.1:11434 and the API on 127.0.0.1:8000. Open `/legal.html`. Ctrl+C stops the API; the model stays available. Logs and model PID are under `data/`. Without a working LLM, source retrieval and validated template drafts remain available. Optional hosted keys in `.env` can send request context to that provider; blank keys use the local setup.

`configure_local_mode.py` also enables `LEGAL_WEB_FALLBACK_ENABLED=true`. If local evidence is insufficient, the agent may read one of three fixed public WIPO IP legislation pages. The question, profile and attachments are not transmitted. Set the flag to `false` for fully offline retrieval. A fetched page is not proof that a statute is current.

```powershell
.\.venv\Scripts\python.exe -m pytest backend -q
.\.venv\Scripts\python.exe -m pip check
```

Tests disable live providers. See `docs/LEGAL_VALIDATION.md` for live checks. This is a local development API; shared authentication and hosting must be integrated before public deployment.
