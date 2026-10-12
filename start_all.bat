@echo off
REM Put this file in the repo root (next to backend\ and services\) and double-click it.
set "ROOT=%~dp0"
set "UPLOADS_DIR=%ROOT%data\uploads"
if not exist "%UPLOADS_DIR%" mkdir "%UPLOADS_DIR%"

REM Optional: set your Groq key here, or leave it out to run without the language model.
REM set LLM_API_KEY=your_key_here

start "BP service :8104" /D "%ROOT%services\bp" cmd /k "python -m uvicorn app.main:app --port 8104"
timeout /t 3 /nobreak >nul
start "Gateway :8000" /D "%ROOT%backend" cmd /k "python -m uvicorn app.main:app --port 8000"
timeout /t 4 /nobreak >nul
start "" http://localhost:8000
