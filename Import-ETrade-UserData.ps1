# Import transferred E*TRADE user data into an install folder.
# Merges configs, tokens, and output/ over the target app root.
param(
    [string]$DataDir = "",
    [string]$InstallDir = "",
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$m) { Write-Host "[import] $m" }

# Resolve data dir: param, script folder (if transfer package), or Desktop export
if (-not $DataDir) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $here "TRANSFER_MANIFEST.json")) {
        $DataDir = $here
    } elseif (Test-Path (Join-Path $here "etrade_config.json")) {
        $DataDir = $here
    } else {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $guess = Join-Path $desktop "ETrade-UserData-Transfer"
        if (Test-Path $guess) { $DataDir = $guess }
    }
}
if (-not $DataDir -or -not (Test-Path -LiteralPath $DataDir)) {
    throw "Could not find data folder. Pass -DataDir path to ETrade-UserData-Transfer"
}
$DataDir = (Resolve-Path -LiteralPath $DataDir).Path

# Resolve install dir
if (-not $InstallDir) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\ETrade Unified Trader"),
        (Join-Path $env:USERPROFILE "Finance"),
        "C:\Users\Box One\Finance"
    )
    # If script lives inside an app root that has unified_trader_gui.py, use that
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $here "unified_trader_gui.py")) {
        $candidates = @($here) + $candidates
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path (Join-Path $c "unified_trader_gui.py"))) {
            $InstallDir = $c
            break
        }
    }
}
if (-not $InstallDir -or -not (Test-Path (Join-Path $InstallDir "unified_trader_gui.py"))) {
    throw "InstallDir not found. Pass -InstallDir to the ETrade Unified Trader folder (must contain unified_trader_gui.py)."
}
$InstallDir = (Resolve-Path -LiteralPath $InstallDir).Path

Write-Step "Data:    $DataDir"
Write-Step "Install: $InstallDir"
if ($WhatIf) { Write-Step "WhatIf — no files will be written" }

$copied = 0

function Import-Tree([string]$From, [string]$ToRel) {
    if (-not (Test-Path -LiteralPath $From)) { return }
    $destRoot = if ($ToRel) { Join-Path $InstallDir $ToRel } else { $InstallDir }
    Get-ChildItem -LiteralPath $From -Recurse -File -Force | ForEach-Object {
        $rel = $_.FullName.Substring($From.Length).TrimStart('\', '/')
        $dest = Join-Path $destRoot $rel
        $script:copied++
        if ($WhatIf) {
            Write-Host "  would copy $rel"
            return
        }
        $parent = Split-Path -Parent $dest
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
    }
}

# Root-level data files
foreach ($name in @(
        "etrade_config.json",
        "short_etrade_config.json",
        "etrade_tokens.json",
        "short_etrade_tokens.json",
        "config.json",
        "ui_prefs.json"
    )) {
    $src = Join-Path $DataDir $name
    if (Test-Path -LiteralPath $src) {
        $dest = Join-Path $InstallDir $name
        if ($WhatIf) {
            Write-Host "  would copy $name"
        } else {
            Copy-Item -LiteralPath $src -Destination $dest -Force
        }
        $copied++
        Write-Step "  + $name"
    }
}

# config/
$configSrc = Join-Path $DataDir "config"
if (Test-Path -LiteralPath $configSrc) {
    Write-Step "Importing config/..."
    Import-Tree $configSrc "config"
}

# output/
$outputSrc = Join-Path $DataDir "output"
if (Test-Path -LiteralPath $outputSrc) {
    Write-Step "Importing output/..."
    Import-Tree $outputSrc "output"
}

# Clear stale locks so worker can start cleanly
if (-not $WhatIf) {
    $locks = @(
        "output\etrade_worker.lock",
        "output\ensure_silent_worker.lock",
        "output\finance_supervisor.lock",
        "output\short_worker.lock",
        "output\pipeline_watchdog.lock"
    )
    foreach ($rel in $locks) {
        $p = Join-Path $InstallDir $rel
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
            Write-Step "  cleared $rel"
        }
    }
}

Write-Host ""
Write-Step "DONE — imported $copied files into $InstallDir"
Write-Host "Next: launch ETrade Unified Trader → Settings → Connect if tokens expired."
exit 0
