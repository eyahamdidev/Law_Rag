@echo off
REM One-time setup: Python environments, packages, API keys, search index. Options: -Gpu  -BuildIndex
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
pause
