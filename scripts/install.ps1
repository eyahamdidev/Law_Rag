# One-time setup on Windows. Run it with install.cmd (double-click, or type install in a terminal).
# Safe to run again: existing environments are updated, an existing .env is kept.
#
#   install.cmd            CPU (works on every laptop)
#   install.cmd -Gpu       also use an NVIDIA/AMD/Intel GPU for search (DirectML)
#   install.cmd -BuildIndex  build the search index at the end without asking (about 60 min on CPU)
param([switch]$Gpu, [switch]$BuildIndex)

# Exit codes are checked explicitly: with "Stop", Windows PowerShell 5.1 turns harmless warnings
# that pip or pytest print on stderr into fatal errors.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Say($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    OK  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "    !!  $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host ""; Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }

# A Python whose version is one of $Versions (first found wins), via the py launcher, else python.exe.
function Find-Python([string[]]$Versions) {
    foreach ($v in $Versions) {
        try {
            $out = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return @{ Exe = $out.Trim(); Version = $v } }
        } catch {}
    }
    try {
        $v = (& python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $Versions -contains $v.Trim()) {
            return @{ Exe = (& python -c "import sys; print(sys.executable)").Trim(); Version = $v.Trim() }
        }
    } catch {}
    return $null
}

# Create (or update) one virtual environment and install a requirements file into it.
function Setup-Venv([string]$Name, [string]$Requirements, [string[]]$Versions, [string]$Why) {
    Say "Environment $Name ($Why)"
    $python = Join-Path $Root "$Name\Scripts\python.exe"
    if (Test-Path $python) {
        Ok "$Name already exists ($(& $python --version)); updating packages"
    } else {
        $found = Find-Python $Versions
        if (-not $found) { Fail "$Name needs Python $($Versions -join ' or '). Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run install.cmd again." }
        Write-Host "    creating $Name with Python $($found.Version)"
        & $found.Exe -m venv (Join-Path $Root $Name)
        if ($LASTEXITCODE -ne 0) { Fail "could not create $Name" }
    }
    & $python -m pip install --upgrade pip --quiet --disable-pip-version-check
    & $python -m pip install -r (Join-Path $Root $Requirements) --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { Fail "installing $Requirements into $Name failed (see the messages above)" }
    Ok "$Name ready"
}

Write-Host "Tunisian Legal & Financial Assistant - setup" -ForegroundColor White

# 1. Large PDFs are stored with Git LFS; a missing LFS checkout silently drops a law text.
Say "Checking the law PDFs (Git LFS)"
$pointers = @()
try {
    foreach ($f in (& git lfs ls-files -n 2>$null)) {
        $path = Join-Path $Root $f
        if ((Test-Path $path) -and ((Get-Item $path).Length -lt 1024) -and ((Get-Content $path -TotalCount 1) -like "version https://git-lfs*")) { $pointers += $f }
    }
} catch {}
if ($pointers.Count) {
    Warn "$($pointers.Count) file(s) are LFS pointers, not PDFs. Run: git lfs install ; git lfs pull"
} else { Ok "LFS files present" }

# 2. Three environments: the services need different library versions.
# fastembed pulls the CPU package "onnxruntime", which overwrites onnxruntime-directml: a machine
# already set up for the GPU keeps it (the GPU step below reinstalls it after the requirements).
$mainPython = Join-Path $Root ".venv\Scripts\python.exe"
if ((Test-Path $mainPython) -and (& $mainPython -m pip show onnxruntime-directml 2>$null)) { $Gpu = $true }
Setup-Venv ".venv"       "requirements.txt"                  @("3.12", "3.11", "3.10") "main app, Python 3.10-3.12"
Setup-Venv ".venv-fraud" "requirements-fraud.txt"            @("3.12", "3.11", "3.13") "fraud service, Python 3.11+"
Setup-Venv ".venv-bp"    "services\bp\requirements-dev.txt"  @("3.12", "3.13")         "business-plan service, Python 3.12+"

if ($Gpu) {
    Say "GPU search (DirectML)"
    & "$Root\.venv\Scripts\python.exe" -m pip uninstall -y onnxruntime --quiet 2>$null
    & "$Root\.venv\Scripts\python.exe" -m pip install --no-deps --force-reinstall onnxruntime-directml --quiet
    if ($LASTEXITCODE -ne 0) { Warn "onnxruntime-directml did not install; search stays on CPU" } else { Ok "onnxruntime-directml installed" }
}

# 3. .env with the API keys (never committed: .env is git-ignored).
Say "API keys (.env)"
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $Root ".env.example") $envFile; Ok "created .env from .env.example" } else { Ok ".env already exists (kept)" }
$lines = Get-Content $envFile -Encoding UTF8
function Get-EnvValue($name) { foreach ($l in $lines) { if ($l -match "^$name=(.*)$") { return $Matches[1].Trim() } }; return "" }
function Set-EnvValue($name, $value) {
    $script:lines = @($script:lines | ForEach-Object { if ($_ -match "^$name=") { "$name=$value" } else { $_ } })
}
foreach ($key in @(@("GROQ_API_KEY", "https://console.groq.com/keys"), @("GEMINI_API_KEY", "https://aistudio.google.com/apikey"))) {
    if (-not (Get-EnvValue $key[0])) {
        $value = Read-Host "    Paste your own $($key[0]) (free at $($key[1])), or press Enter to skip"
        if ($value) { Set-EnvValue $key[0] $value.Trim() }
    }
}
if ($Gpu) { Set-EnvValue "EMBEDDING_DEVICE" "dml" }
[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding $false))
if (Get-EnvValue "GROQ_API_KEY") { Ok "Groq key set" } else { Warn "no Groq key: answers will list passages instead of being written (add it to .env later)" }
New-Item -ItemType Directory -Force (Join-Path $Root "data\uploads") | Out-Null

# 4. The search index (data/index and data/qdrant), built from the PDFs once.
Say "Search index"
$haveIndex = (Test-Path (Join-Path $Root "data\index\structural\chunks.jsonl")) -and (Test-Path (Join-Path $Root "data\qdrant"))
if ($haveIndex) {
    Ok "index found in data\"
} else {
    Warn "no index yet. Either unzip a teammate's data\index and data\qdrant into data\ (fast), or build it now."
    $build = $BuildIndex
    if (-not $build) { $build = ((Read-Host "    Build it now? About 60 min on CPU, 10 on a GPU, downloads 1.1 GB once [y/N]") -match "^[yYoO]") }
    if ($build) {
        Push-Location (Join-Path $Root "backend")
        & "$Root\.venv\Scripts\python.exe" -m app.modules.rag.ingestion.pipeline --strategy structural
        $code = $LASTEXITCODE
        Pop-Location
        if ($code -ne 0) { Fail "index build failed (see above)" } else { Ok "index built" }
    } else { Warn "skipped: run install.cmd -BuildIndex later, or copy the index" }
}

# 5. Quick self-test: no key, GPU or index needed.
Say "Self-test"
Push-Location (Join-Path $Root "backend")
& "$Root\.venv\Scripts\python.exe" -m pytest -q 2>&1 | Select-Object -Last 1
Pop-Location

Write-Host ""
Write-Host "Setup finished. Start everything with: run.cmd   (stop with: stop.cmd)" -ForegroundColor Green
