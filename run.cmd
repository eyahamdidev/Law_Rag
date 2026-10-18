@echo off
REM Start the main app and the fraud and business-plan services, then open the browser. Options: -WithN8n  -NoBrowser
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scriptsun.ps1" %*
pause
