@echo off
REM Put this file in the repo root (next to backend\ and services\) and double-click it.
set "ROOT=%~dp0"
set "UPLOADS_DIR=%ROOT%data\uploads"
if not exist "%UPLOADS_DIR%" mkdir "%UPLOADS_DIR%"

REM ---- Language model: local Ollama (default) -------------------------------------
REM Ollama must be running (the llama icon in the tray, or run: ollama serve).
set "LLM_BASE_URL=http://localhost:11434/v1"
set "LLM_API_KEY=ollama"
set "LLM_MODEL_MAIN=qwen2.5:7b"
set "LLM_MODEL_FAST=qwen2.5:7b"
set "LLM_TIMEOUT_S=180"
REM Reading and judging plans stays rule-based (fast). The model only writes: plan wording and drafts.
set "BP_LLM_STEPS=plan_writer,drafts"
set "BP_TIMEOUT_S=600"
REM To switch to Groq instead, comment the lines above and use:
REM set LLM_API_KEY=your_groq_key
REM To run with no model at all: set BP_LLM=off

python -c "import pymupdf" 2>nul || python -m pip install -q pymupdf

start "BP service :8104" /D "%ROOT%services\bp" cmd /k "python -m uvicorn app.main:app --port 8104"
timeout /t 3 /nobreak >nul
start "Gateway :8000" /D "%ROOT%backend" cmd /k "python -m uvicorn app.main:app --port 8000"
timeout /t 4 /nobreak >nul
start "" http://localhost:8000
