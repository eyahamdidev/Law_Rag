# Stop the services started by run.cmd. stop.cmd -WithN8n also stops n8n.
param([switch]$WithN8n)
$Root = Split-Path -Parent $PSScriptRoot

function Get-EnvValue([string]$Name) {
    $path = Join-Path $Root ".env"
    if (-not (Test-Path $path)) { return "" }
    foreach ($line in Get-Content $path -Encoding UTF8) {
        if ($line -match "^$Name=(.*)$") { return $Matches[1].Trim() }
    }
    return ""
}

function Get-FraudPort {
    $url = Get-EnvValue "FRAUD_SERVICE_URL"
    if ($url -match ":(\d+)(/|$)") { return [int]$Matches[1] }
    return 8100
}

function Stop-ListeningPython([int]$Port, [string]$Label) {
    $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    if (-not $owners) {
        Write-Host "  $Label was not running" 
        return
    }
    foreach ($id in $owners) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -match "python") {
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
            Write-Host "  stopped $Label (port $Port)" -ForegroundColor Green
        } elseif ($proc) {
            Write-Host "  left $($proc.ProcessName) on port $Port (not our Python service)" -ForegroundColor Yellow
        }
    }
}

Stop-ListeningPython 8000 "Main app"
Stop-ListeningPython (Get-FraudPort) "Fraud service"
Stop-ListeningPython 8104 "Business-plan service"

if ($WithN8n -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    & docker compose -f "$Root\docker-compose.n8n.yml" down 2>&1 | Out-Null
    Write-Host "  stopped n8n" -ForegroundColor Green
}
