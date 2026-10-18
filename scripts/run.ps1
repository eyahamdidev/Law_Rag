# Start the assistant on Windows. Run it with run.cmd (double-click, or type run in a terminal).
#
#   run.cmd              main app + fraud service + business-plan service, then opens the browser
#   run.cmd -WithN8n     also starts n8n in Docker (needs Docker Desktop running)
#   run.cmd -NoBrowser   do not open the browser
#
# Each service opens in its own window with its log; closing a window stops that service.
# stop.cmd stops all of them.
param([switch]$WithN8n, [switch]$NoBrowser)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Ok($text) { Write-Host "  OK  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  !!  $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "ERROR: $text" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }

foreach ($venv in @(".venv", ".venv-fraud", ".venv-bp")) {
    if (-not (Test-Path (Join-Path $Root "$venv\Scripts\python.exe"))) { Fail "$venv is missing. Run install.cmd first." }
}
if (-not (Test-Path (Join-Path $Root ".env"))) { Fail ".env is missing. Run install.cmd first." }
if (-not (Test-Path (Join-Path $Root "data\index\structural\chunks.jsonl"))) {
    Warn "no search index in data\ (run install.cmd -BuildIndex, or copy a teammate's data\index and data\qdrant). Answers will be empty."
}

function Test-Port([int]$Port) { return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) }

# Opens a PowerShell window that runs $Command in $Dir. The command reads secrets from .env
# itself, so no key ever appears on a command line.
function Start-ServiceWindow([string]$Title, [int]$Port, [string]$Dir, [string]$Command) {
    if (Test-Port $Port) { Ok "$Title already running on port $Port"; return }
    $script = "`$host.UI.RawUI.WindowTitle = '$Title (port $Port)'; Set-Location '$Dir'; $Command"
    Start-Process powershell -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $script) | Out-Null
    Ok "$Title starting on port $Port"
}

# Reads one value from .env inside the service window.
$readEnv = "function EnvValue(`$n) { foreach (`$l in Get-Content '$Root\.env' -Encoding UTF8) { if (`$l -match ('^' + `$n + '=(.*)$')) { return `$Matches[1].Trim() } }; return '' }"

Write-Host "Starting the Tunisian Legal & Financial Assistant" -ForegroundColor White

Start-ServiceWindow "Main app" 8000 "$Root\backend" `
    "& '$Root\.venv\Scripts\python.exe' -m uvicorn app.main:app --port 8000"

Start-ServiceWindow "Fraud service" 8100 $Root `
    "& '$Root\.venv-fraud\Scripts\python.exe' -m fraud_detection serve --port 8100"

# The business-plan service uses Groq with the same key, the models a free key allows, and
# BP_VECTOR_STORE=off (it would otherwise wait on an absent Ollama: ~7 s per plan section).
Start-ServiceWindow "Business-plan service" 8104 "$Root\services\bp" (
    "$readEnv; " +
    "`$env:LLM_BASE_URL = 'https://api.groq.com/openai/v1'; `$env:LLM_API_KEY = (EnvValue 'GROQ_API_KEY'); " +
    "`$env:LLM_MODEL_MAIN = (EnvValue 'LLM_MODEL_MAIN'); `$env:LLM_MODEL_FAST = (EnvValue 'LLM_MODEL_FAST'); " +
    "`$env:BP_LLM_STEPS = (EnvValue 'BP_LLM_STEPS'); `$env:LLM_TIMEOUT_S = '45'; `$env:BP_TIMEOUT_S = '170'; " +
    "`$env:BP_VECTOR_STORE = 'off'; `$env:UPLOADS_DIR = '$Root\data\uploads'; `$env:PYTHONIOENCODING = 'utf-8'; " +
    "& '$Root\.venv-bp\Scripts\python.exe' -m uvicorn app.main:app --port 8104")

if ($WithN8n) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) { Warn "Docker not found: n8n not started (install Docker Desktop)" }
    else {
        & docker compose -f "$Root\docker-compose.n8n.yml" up -d 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok "n8n starting on http://localhost:5678" } else { Warn "n8n did not start: is Docker Desktop running?" }
    }
}

# Wait until each service answers. The main app also loads the search models (about a minute).
Write-Host ""
Write-Host "Waiting for the services (the first start can take 1-2 minutes)..."
$checks = @(@("Main app", "http://127.0.0.1:8000/api/health"), @("Fraud service", "http://127.0.0.1:8100/health"), @("Business-plan service", "http://127.0.0.1:8104/health"))
$deadline = (Get-Date).AddSeconds(240)
foreach ($c in $checks) {
    $up = $false
    while (-not $up -and (Get-Date) -lt $deadline) {
        try { $null = Invoke-WebRequest $c[1] -UseBasicParsing -TimeoutSec 3; $up = $true } catch { Start-Sleep -Seconds 2 }
    }
    if ($up) { Ok "$($c[0]) is up" } else { Warn "$($c[0]) did not answer: look at its window for the error" }
}

Write-Host ""
Write-Host "Ready:" -ForegroundColor Green
Write-Host "  Web interface   http://127.0.0.1:8000"
Write-Host "  API docs        http://127.0.0.1:8000/docs"
if ($WithN8n) { Write-Host "  n8n             http://localhost:5678   (intake form: http://localhost:5678/form/founder-intake)" }
Write-Host "  Stop everything with stop.cmd"
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:8000" }
