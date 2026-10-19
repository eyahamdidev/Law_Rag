# Stop the services started by run.cmd (ports 8000, 8100, 8104). stop.cmd -WithN8n also stops n8n.
param([switch]$WithN8n)
$Root = Split-Path -Parent $PSScriptRoot
foreach ($p in @(@(8000, "Main app"), @(8100, "Fraud service"), @(8104, "Business-plan service"))) {
    $owners = Get-NetTCPConnection -LocalPort $p[0] -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    if ($owners) {
        foreach ($id in $owners) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
        Write-Host "  stopped $($p[1]) (port $($p[0]))" -ForegroundColor Green
    } else { Write-Host "  $($p[1]) was not running" }
}
if ($WithN8n -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    & docker compose -f "$Root\docker-compose.n8n.yml" down 2>&1 | Out-Null
    Write-Host "  stopped n8n" -ForegroundColor Green
}
