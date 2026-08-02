#Requires -Version 5.1
<#
.SYNOPSIS
  Stop all Finance/E*TRADE pipeline + trading processes and remove autostart install.

.DESCRIPTION
  Used on BOXONE before switching to dual-PC pipeline-only mode.
  Does NOT delete the Finance folder, configs, tokens, or output/ research data.
  Removes: scheduled tasks, Startup shortcuts, Run keys, Start Menu links,
  and kills matching python/wscript processes for this install.
#>
param(
    [string]$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [switch]$KeepDesktopShortcuts
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path $Root).Path
Write-Host "=== Uninstall Finance app autostart (root=$Root) ==="

# --- 1. Kill pipeline / worker / GUI processes tied to this install ---
function Stop-FinanceProcesses {
    $patterns = @(
        [regex]::Escape($Root),
        "etrade_worker\.py",
        "short_worker\.py",
        "finance_agents_gui\.py",
        "finance_supervisor\.py",
        "ensure_silent_worker\.py",
        "run_pipeline_loop\.py",
        "run_backtest_loop\.py",
        "run_market_predictor_loop\.py",
        "day_trader\.py",
        "mobile_monitor\.py"
    )
    $joined = ($patterns -join "|")
    $killed = @()
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) { return }
        if ($cmd -notmatch $joined) { return }
        # Do not kill this uninstall script's shell
        if ($cmd -match "Uninstall-FinanceApp") { return }
        try {
            Write-Host "  Kill PID $($_.ProcessId): $($_.Name) — $($cmd.Substring(0, [Math]::Min(120, $cmd.Length)))"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            $killed += $_.ProcessId
        } catch {
            Write-Host "  Could not kill $($_.ProcessId): $($_.Exception.Message)"
        }
    }
    # taskkill residual python trees that still hold worker lock files
    Start-Sleep -Seconds 1
    return $killed
}

Write-Host "`n[1/4] Stopping Finance processes..."
$killed = Stop-FinanceProcesses
Write-Host "  Killed $($killed.Count) process(es)."

# --- 2. Scheduled tasks ---
$taskNames = @(
    "Finance ETrade Background Service",
    "Finance ETrade Worker Watchdog",
    "Finance ETrade Worker",
    "Finance ETrade Live Trading",
    "Finance ETrade Day Trading",
    "Finance ETrade Short Background",
    "Finance ETrade Short Worker"
)
Write-Host "`n[2/4] Removing scheduled tasks..."
foreach ($name in $taskNames) {
    try {
        $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($t) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
            Write-Host "  Removed task: $name"
        }
    } catch {
        try {
            schtasks /Delete /F /TN $name 2>$null | Out-Null
            Write-Host "  Removed task (schtasks): $name"
        } catch {
            Write-Host "  Skip task $name : $($_.Exception.Message)"
        }
    }
}

# --- 3. Startup shortcuts + Run keys ---
Write-Host "`n[3/4] Removing Startup / Run keys / Start Menu..."
$startup = [Environment]::GetFolderPath("Startup")
$programs = [Environment]::GetFolderPath("Programs")
$desktop = [Environment]::GetFolderPath("Desktop")
$linkNames = @(
    "ETrade Background Service.lnk",
    "ETrade Short Background Service.lnk",
    "ETrade Trader.lnk",
    "ETrade Unified Trader.lnk",
    "ETrade Short Trader.lnk",
    "Finance Agents.lnk",
    "Start Silent Worker Only.lnk"
)
foreach ($dir in @($startup, $programs)) {
    foreach ($ln in $linkNames) {
        $p = Join-Path $dir $ln
        if (Test-Path $p) {
            Remove-Item $p -Force -ErrorAction SilentlyContinue
            Write-Host "  Removed: $p"
        }
    }
}
if (-not $KeepDesktopShortcuts) {
    foreach ($ln in $linkNames) {
        $p = Join-Path $desktop $ln
        if (Test-Path $p) {
            Remove-Item $p -Force -ErrorAction SilentlyContinue
            Write-Host "  Removed desktop: $p"
        }
    }
}

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runNames = @(
    "FinanceETradeBackgroundService",
    "FinanceETradeShortBackgroundService",
    "FinanceETradeUnified",
    "ETradeUnifiedTrader",
    "ETradeTrader",
    "FinanceAgents"
)
foreach ($rn in $runNames) {
    try {
        if (Get-ItemProperty -Path $runKey -Name $rn -ErrorAction SilentlyContinue) {
            Remove-ItemProperty -Path $runKey -Name $rn -Force -ErrorAction SilentlyContinue
            Write-Host "  Removed Run key: $rn"
        }
    } catch {}
}

# ProgramData icon dir (optional — leave icons if other machines use it)
# Do not delete config/tokens/output

# --- 4. Clear worker locks so next start is clean ---
Write-Host "`n[4/4] Clearing worker locks..."
$out = Join-Path $Root "output"
foreach ($lock in @("etrade_worker.lock", "short_worker.lock")) {
    $lp = Join-Path $out $lock
    if (Test-Path $lp) {
        Remove-Item $lp -Force -ErrorAction SilentlyContinue
        Write-Host "  Removed $lp"
    }
}

# Second pass kill (respawn from watchdog may race)
Start-Sleep -Seconds 2
$killed2 = Stop-FinanceProcesses
if ($killed2.Count -gt 0) {
    Write-Host "  Second pass killed $($killed2.Count) more."
}

Write-Host "`n=== Uninstall complete ==="
Write-Host "Preserved: configs, tokens, output/, .venv, source tree under $Root"
Write-Host "Next: git pull, set deployment.json role=pipeline, run Install-PipelineOnly.ps1"
exit 0
