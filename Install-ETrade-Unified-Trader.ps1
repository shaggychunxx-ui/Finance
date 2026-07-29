# Install / repair E*TRADE Unified Trader on this PC.
# Creates local .venv, installs deps, seeds config examples, desktop shortcut.
# Safe for Grok / unattended: non-zero exit on failure.
param(
    [string]$InstallDir = "",
    [switch]$InPlace
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[install] $Message"
}

function Find-Python {
    $candidates = @()
    foreach ($cmd in @("py", "python", "python3")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) { $candidates += $found.Source }
    }
    # Common per-user installs
    $local = $env:LOCALAPPDATA
    if ($local) {
        foreach ($ver in @("Python312", "Python311", "Python310", "Python313")) {
            $p = Join-Path $local "Programs\Python\$ver\python.exe"
            if (Test-Path $p) { $candidates += $p }
        }
    }
    foreach ($p in $candidates) {
        try {
            if ($p -match 'WindowsApps\\python') { continue }
            $out = & $p -c "import sys; assert sys.version_info[:2] >= (3, 10); import tkinter; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                return $out.Trim()
            }
        } catch { }
    }
    return $null
}

if ($InstallDir -and -not $InPlace) {
    # Reserved for future copy-from-media installs
    $Root = $InstallDir
} elseif ($InstallDir -and $InPlace) {
    $Root = $InstallDir
} else {
    $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
}

if (-not (Test-Path (Join-Path $Root "unified_trader_gui.py"))) {
    throw "InstallDir does not look like ETrade Unified Trader: $Root"
}

Set-Location -LiteralPath $Root
Write-Step "Root: $Root"

$python = Find-Python
if (-not $python) {
    Write-Host ""
    Write-Host "Python 3.10+ with tkinter was not found."
    Write-Host "Install from https://www.python.org/downloads/"
    Write-Host "  - Check 'Add python.exe to PATH'"
    Write-Host "  - Keep tcl/tk (default)"
    Write-Host "Then re-run this installer."
    exit 2
}
Write-Step "Python: $python"

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
$venvPip = Join-Path $Root ".venv\Scripts\pip.exe"
if (-not (Test-Path $venvPy)) {
    Write-Step "Creating .venv..."
    & $python -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
} else {
    Write-Step ".venv already present"
}

Write-Step "Installing requirements..."
& $venvPy -m pip install --upgrade pip -q
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
$req = Join-Path $Root "requirements.txt"
if (-not (Test-Path $req)) { throw "Missing requirements.txt" }
& $venvPy -m pip install -r $req
if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }

# Seed configs from examples (never overwrite existing secrets)
function Copy-ExampleIfMissing([string]$ExampleName, [string]$TargetName) {
    $example = Join-Path $Root $ExampleName
    $target = Join-Path $Root $TargetName
    if ((Test-Path $example) -and -not (Test-Path $target)) {
        Copy-Item -LiteralPath $example -Destination $target -Force
        Write-Step "Created $TargetName from example — add your API keys."
    }
}
Copy-ExampleIfMissing "etrade_config.example.json" "etrade_config.json"
Copy-ExampleIfMissing "short_etrade_config.example.json" "short_etrade_config.json"
Copy-ExampleIfMissing "config.example.json" "config.json"

# Desktop + Start Menu shortcuts
$refresh = Join-Path $Root "refresh_unified_desktop_icon.ps1"
if (Test-Path $refresh) {
    Write-Step "Creating desktop / Start Menu shortcuts..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $refresh
} else {
    $bat = Join-Path $Root "ETrade Unified Trader.bat"
    if (-not (Test-Path $bat)) {
        @"
@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "PY=%~dp0.venv\Scripts\python.exe"
set "GUI=%~dp0unified_trader_gui.py"
if not exist "%PY%" (
  echo Run Install-ETrade-Unified-Trader.ps1 first.
  pause
  exit /b 1
)
if exist "%PYW%" (start "ETradeUnified" /D "%~dp0" "%PYW%" "%GUI%") else (start "ETradeUnified" /D "%~dp0" "%PY%" "%GUI%")
"@ | Set-Content -Path $bat -Encoding ASCII
    }
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnkPath = Join-Path $desktop "ETrade Unified Trader.lnk"
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $bat
    $lnk.WorkingDirectory = $Root
    $icon = Join-Path $Root "etrade_trader.ico"
    if (-not (Test-Path $icon)) { $icon = Join-Path $Root "etrade_short_trader.ico" }
    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
    $lnk.Description = "ETrade Unified Trader"
    $lnk.Save()
    Write-Step "Shortcut: $lnkPath"
}

# Ensure output dir exists
New-Item -ItemType Directory -Force -Path (Join-Path $Root "output") | Out-Null

Write-Host ""
Write-Step "SUCCESS"
Write-Host "  Launch: Desktop → ETrade Unified Trader"
Write-Host "  Config: $Root\etrade_config.json"
Write-Host "  Optional background worker: Install ETrade Background.bat"
exit 0
