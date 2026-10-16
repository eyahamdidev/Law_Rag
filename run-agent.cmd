@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Project Python environment is missing. See LOCAL_SETUP.md.
  exit /b 1
)
".venv\Scripts\python.exe" scripts\local_runtime.py
echo Open http://127.0.0.1:8000/legal.html for legal guidance and contract drafting.
".venv\Scripts\python.exe" scripts\local_runtime.py --check-api
if not errorlevel 1 (
  echo The legal API is already running. Use the link above.
  exit /b 0
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
if errorlevel 1 pause
