# Export E*TRADE Unified Trader saved data for transfer to another PC.
# Default: configs + tokens + current state + trade history journals.
# Does NOT include huge price/archive caches unless -Full.
#
# Output (Desktop by default):
#   ETrade-UserData-Transfer\
#   ETrade-UserData-Transfer.zip
param(
    [string]$SourceRoot = "",
    [string]$OutDir = "",
    [switch]$Full,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

if (-not $SourceRoot) {
    $SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path

$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $OutDir) {
    $OutDir = Join-Path $desktop "ETrade-UserData-Transfer"
}

function Write-Step([string]$m) { Write-Host "[export] $m" }

# Wipe previous export folder
if (Test-Path -LiteralPath $OutDir) {
    Write-Step "Removing previous export: $OutDir"
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "output") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "config") | Out-Null

$rootFiles = @(
    "etrade_config.json",
    "short_etrade_config.json",
    "etrade_tokens.json",
    "short_etrade_tokens.json",
    "config.json",
    "ui_prefs.json",
    "oauth_pending.json"
)

$copied = 0
$bytes = [int64]0

function Copy-One([string]$From, [string]$To) {
    $script:copied++
    $script:bytes += (Get-Item -LiteralPath $From).Length
    $parent = Split-Path -Parent $To
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item -LiteralPath $From -Destination $To -Force
}

Write-Step "Source: $SourceRoot"
Write-Step "Dest:   $OutDir"
Write-Step ("Mode:   " + ($(if ($Full) { "FULL (includes archives/price caches)" } else { "STANDARD (configs + state + journals)" })))

# Root secrets / prefs
foreach ($name in $rootFiles) {
    $src = Join-Path $SourceRoot $name
    if (Test-Path -LiteralPath $src) {
        Copy-One $src (Join-Path $OutDir $name)
        Write-Step "  + $name"
    }
}

# Learned agent personalities (user data)
$configDir = Join-Path $SourceRoot "config"
foreach ($name in @(
        "agent_personalities.json",
        "agent_personalities.learned.json",
        "data_apis.json"
    )) {
    $src = Join-Path $configDir $name
    if (Test-Path -LiteralPath $src) {
        Copy-One $src (Join-Path $OutDir "config\$name")
        Write-Step "  + config\$name"
    }
}

$outputSrc = Join-Path $SourceRoot "output"
$outputDst = Join-Path $OutDir "output"

# Skip runtime noise
$skipNameExact = [System.Collections.Generic.HashSet[string]]::new([string[]]@(
        "etrade_worker.lock",
        "ensure_silent_worker.lock",
        "finance_supervisor.lock",
        "pipeline_watchdog.lock",
        "short_worker.lock",
        "oauth_pending.json"
    ), [StringComparer]::OrdinalIgnoreCase)

$skipExt = [System.Collections.Generic.HashSet[string]]::new([string[]]@(
        ".log", ".lock", ".err", ".out", ".pyc"
    ), [StringComparer]::OrdinalIgnoreCase)

# Standard mode: skip bulk cache folders
$skipDirNames = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
if (-not $Full) {
    foreach ($d in @(
            "archive",
            "_agent_tmp",
            "sync_backup_etrade",
            "bars",
            "prices",
            "snapshots",
            "tickers",
            "day_trades"
        )) { [void]$skipDirNames.Add($d) }
}

function Should-SkipFile([System.IO.FileInfo]$file, [string]$relPosix) {
    if ($skipNameExact.Contains($file.Name)) { return $true }
    if ($skipExt.Contains($file.Extension)) { return $true }
    # scratch / test artifacts
    if ($file.Name -match '^(_test|_verify|_run_|_scan_|_agent_|wd_|worker_|pipeline_5x|pipeline_manual)') {
        return $true
    }
    if ($file.Name -match 'heartbeat\.txt$') { return $true }
    return $false
}

if (Test-Path -LiteralPath $outputSrc) {
    Write-Step "Copying output (this may take a minute)..."
    Get-ChildItem -LiteralPath $outputSrc -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $rel = $_.FullName.Substring($outputSrc.Length).TrimStart('\', '/')
        $parts = $rel -split '[\\/]'
        $skip = $false
        foreach ($part in $parts) {
            if ($skipDirNames.Contains($part)) { $skip = $true; break }
        }
        if ($skip) { return }
        if (Should-SkipFile $_ $rel) { return }
        $dest = Join-Path $outputDst $rel
        Copy-One $_.FullName $dest
    }
}

# Manifest
$manifest = @{
    exported_at     = (Get-Date).ToString("o")
    source_root     = $SourceRoot
    mode            = $(if ($Full) { "full" } else { "standard" })
    file_count      = $copied
    total_bytes     = $bytes
    contains_secrets = $true
    notes           = @(
        "Contains API keys and OAuth tokens - treat as confidential.",
        "On the other PC: install the app first, then run Import-ETrade-UserData.ps1",
        "Tokens may need re-auth if E*TRADE invalidates the session."
    )
}
$manifestPath = Join-Path $OutDir "TRANSFER_MANIFEST.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $manifestPath -Encoding UTF8

$readme = @"
E*TRADE Unified Trader - User Data Transfer
==========================================

Exported: $($manifest.exported_at)
Mode:     $($manifest.mode)
Files:    $copied
Size:     $([math]::Round($bytes/1MB, 2)) MB

CONTENTS
--------
- etrade_config.json / short_etrade_config.json  (API keys + strategy)
- etrade_tokens.json                             (OAuth session)
- ui_prefs.json, config.json
- config/agent_personalities*.json               (learned agent prefs)
- output/                                        (portfolio, plans, agent reports,
                                                  trade_history, account_values, short sleeve)

SECURITY
--------
This folder includes secrets (API keys + tokens). Do not email/share publicly.
Delete the transfer folder after import on the new PC.

IMPORT (other PC)
-----------------
1. Ensure Finance runtime is present (agents + etrade_api + worker; no desktop trader UI required)
2. Stop background workers if running
3. Copy this folder onto the new PC
4. Run:
     powershell -ExecutionPolicy Bypass -File Import-ETrade-UserData.ps1 -DataDir "PATH\to\ETrade-UserData-Transfer"
   Or place this folder next to the app and double-click Import-ETrade-UserData.bat
5. Re-auth OAuth if needed (begin_etrade_login.py / finish_etrade_login.py), then Install ETrade Background.bat

FULL export (optional, multi-GB)
--------------------------------
On the source PC:
  powershell -ExecutionPolicy Bypass -File Export-ETrade-UserData.ps1 -Full
"@
Set-Content -Path (Join-Path $OutDir "README_TRANSFER.txt") -Value $readme -Encoding UTF8

# Copy import helpers into the transfer folder so the other PC has them
foreach ($helper in @("Import-ETrade-UserData.ps1", "Import-ETrade-UserData.bat")) {
    $src = Join-Path $SourceRoot $helper
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $OutDir $helper) -Force
    }
}

Write-Step "Copied $copied files ($([math]::Round($bytes/1MB, 2)) MB)"

if (-not $SkipZip) {
    $zipPath = Join-Path $desktop "ETrade-UserData-Transfer.zip"
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Write-Step "Zipping $zipPath ..."
    Compress-Archive -Path $OutDir -DestinationPath $zipPath -CompressionLevel Optimal
    $zipMb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 2)
    Write-Step "Zip ready: $zipPath ($zipMb MB)"
}

Write-Host ""
Write-Host "DONE - transfer folder: $OutDir"
Write-Host "WARNING: includes API keys and OAuth tokens. Keep private."
exit 0
