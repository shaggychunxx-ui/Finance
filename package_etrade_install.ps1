# Package a clean E*TRADE Trader install (no API keys, tokens, or user data).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$stamp = Get-Date -Format "yyyy-MM-dd"
$zipName = "ETrade Trader Install.zip"
$zipPath = Join-Path $desktop $zipName
$stageName = "ETrade-Trader"
$stage = Join-Path $env:TEMP "etrade-install-$([Guid]::NewGuid().ToString('N'))"
$stageRoot = Join-Path $stage $stageName

$excludeDirs = @(
    ".venv", "__pycache__", "output", "build", "dist", ".git", "node_modules"
)
$excludeFiles = @(
    "etrade_config.json",
    "etrade_tokens.json",
    "config.json",
    "oauth_pending.json",
    "ETrade Trader.exe",
    "app_icon.ico",
    "etrade_trader.ico",
    "package_etrade_install.ps1"
)
$excludePatterns = @("*.pyc", "*.pyo", "*.log", "*.lock", "*.db")

function Should-SkipPath {
    param([string]$RelativePath, [bool]$IsDirectory)
    $parts = $RelativePath -split '[\\/]'
    foreach ($part in $parts) {
        if ($excludeDirs -contains $part) { return $true }
    }
    if ($IsDirectory) { return $false }
    $leaf = Split-Path -Leaf $RelativePath
    if ($excludeFiles -contains $leaf) { return $true }
    foreach ($pattern in $excludePatterns) {
        if ($leaf -like $pattern) { return $true }
    }
    return $false
}

function Copy-InstallTree {
    param([string]$Source, [string]$Dest)
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        $rel = $_.Name
        if (Should-SkipPath $rel $_.PSIsContainer) { return }
        $target = Join-Path $Dest $rel
        if ($_.PSIsContainer) {
            Copy-InstallTree -Source $_.FullName -Dest $target
        } else {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}

Write-Host "Staging clean install files..."
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
Copy-InstallTree -Source $root -Dest $stageRoot

$readme = @"
E*TRADE Trader - Install Package
================================

ONE DESKTOP APP
---------------
E*TRADE Trader includes everything in one window:
  Home      - dashboard and automation controls
  Agents    - browse agent research reports (Finance Agents built in)
  Trades    - portfolio, swing, and day trading
  Settings  - E*TRADE API keys and account setup
  Activity  - app log

Finance Agents is not a separate program. The "Finance Agents"
desktop shortcut only opens E*TRADE Trader on the Agents tab.

OPTIONAL BACKGROUND SERVICE
---------------------------
Install ETrade Background.bat adds a second headless process that
keeps agents and trading running when the GUI is closed. The GUI
alone is enough if you leave the app open.

This package does NOT include:
  - Your E*TRADE API keys
  - OAuth tokens
  - Saved account choices
  - Trading history, logs, or agent output

INSTALL (new PC or fresh setup)
-------------------------------
1. Unzip anywhere (e.g. Documents\Finance)
2. Double-click: Install ETrade Trader.bat
3. Edit etrade_config.json with your E*TRADE consumer key/secret
   (created from etrade_config.example.json on first install)
4. Launch "ETrade Trader" from the desktop shortcut
5. Click Connect, then pick your account in Settings
6. Optional: Install ETrade Background.bat for login startup automation

PHONE MONITOR (any network)
---------------------------
1. Start Mobile Server.bat — monitor on your home Wi-Fi
2. Start Mobile Remote Access.bat — Cloudflare tunnel URL for cellular/away
3. Open the URL on your phone (add ?token= from the console to the bookmark)
4. UI matches desktop tabs: Home, Agents, Trades, Activity

REQUIREMENTS
------------
  - Windows 10/11
  - Python 3.10+ on PATH (installer creates a local .venv)
  - E*TRADE developer API keys (https://developer.etrade.com)

Packaged: $stamp
"@

Set-Content -Path (Join-Path $stageRoot "INSTALL.txt") -Value $readme -Encoding UTF8

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Write-Host "Creating $zipPath ..."
Compress-Archive -Path $stageRoot -DestinationPath $zipPath -CompressionLevel Optimal
if (Test-Path -LiteralPath $stage) {
    try {
        [System.IO.Directory]::Delete($stage, $true)
    } catch {
        cmd /c "rmdir /s /q `"$stage`"" | Out-Null
    }
}

$sizeMb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 2)
Write-Host ""
Write-Host "Done: $zipPath ($sizeMb MB)"
Write-Host "No API keys, tokens, or user data included."