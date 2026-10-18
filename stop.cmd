@echo off
REM Stop the services started by run.cmd. Option: -WithN8n
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1" %*
pause
