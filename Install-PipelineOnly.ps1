#Requires -Version 5.1
<#
.SYNOPSIS
  Install BOXONE as dual-PC **pipeline-only** host (no trading GUI autostart).

.DESCRIPTION
  - Writes deployment.json role=pipeline
  - Disables trading flags in etrade configs (practice-safe)
  - Installs silent pipeline worker + 5-min watchdog only (no GUI at login)
  - Does not start Unified Trader / order placement
#>
param(
    [string]$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$SharedRoot = "\\10.10.10.1\HelperDrop\FinanceShare"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path
Write-Host "=== Install pipeline-only (BOXONE) root=$Root ==="
Write-Host "Shared root: $SharedRoot"

# 1) deployment.json
$dep = @{
    role                            = "pipeline"
    shared_root                     = $SharedRoot
    quote_publish_interval_seconds  = 60
    sync_interval_seconds           = 30
    publish_quotes                  = $false
    consume_shared_quotes           = $true
    prefer_dry_run                  = $true
} | ConvertTo-Json
$depPath = Join-Path $Root "deployment.json"
# UTF-8 no BOM
[System.IO.File]::WriteAllText($depPath, $dep + "`n", (New-Object System.Text.UTF8Encoding $false))
Write-Host "Wrote $depPath"

# 2) Force trading off in configs (keep secrets)
function Set-TradingOff([string]$ConfigPath) {
    if (-not (Test-Path $ConfigPath)) {
        Write-Host "  Skip missing $ConfigPath"
        return
    }
    $raw = Get-Content $ConfigPath -Raw -Encoding UTF8
    if ($raw[0] -eq [char]0xFEFF) { $raw = $raw.Substring(1) }
    $j = $raw | ConvertFrom-Json
    if (-not $j.background_worker) {
        $j | Add-Member -NotePropertyName background_worker -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    $bw = $j.background_worker
    $bw | Add-Member -NotePropertyName dry_run -NotePropertyValue $true -Force
    $bw | Add-Member -NotePropertyName auto_execute -NotePropertyValue $false -Force
    $bw | Add-Member -NotePropertyName live_trading -NotePropertyValue $false -Force
    $bw | Add-Member -NotePropertyName day_trading -NotePropertyValue $false -Force
    $bw | Add-Member -NotePropertyName paused -NotePropertyValue $false -Force
    # paused=false so pipeline service loop keeps researching; trading flags already off
    $j | Add-Member -NotePropertyName deployment -NotePropertyValue ([pscustomobject]@{
            role           = "pipeline"
            shared_root    = $SharedRoot
            prefer_dry_run = $true
        }) -Force
    $json = $j | ConvertTo-Json -Depth 40
    [System.IO.File]::WriteAllText($ConfigPath, $json + "`n", (New-Object System.Text.UTF8Encoding $false))
    Write-Host "  Trading off + pipeline role: $ConfigPath"
}
Set-TradingOff (Join-Path $Root "etrade_config.json")
Set-TradingOff (Join-Path $Root "short_etrade_config.json")

# 3) Ensure share reachable (warn only)
if (-not (Test-Path $SharedRoot)) {
    Write-Warning "Shared root not reachable yet: $SharedRoot — fix Ethernet/SMB before market open."
} else {
    New-Item -ItemType Directory -Force -Path (Join-Path $SharedRoot "pipeline"), (Join-Path $SharedRoot "broker") | Out-Null
    Write-Host "Share OK: $SharedRoot"
}

# 4) venv
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating .venv..."
    python -m venv (Join-Path $Root ".venv")
    & (Join-Path $Root ".venv\Scripts\python.exe") -m pip install -r (Join-Path $Root "requirements.txt")
    $py = Join-Path $Root ".venv\Scripts\python.exe"
}
if (-not (Test-Path $py)) { throw "Python venv missing at $py" }

# 5) Autostart: silent worker only (no GUI)
$serviceLauncher = Join-Path $Root "Start Silent Worker Only.vbs"
if (-not (Test-Path $serviceLauncher)) {
    $serviceLauncher = Join-Path $Root "Start ETrade Background Service.vbs"
}
if (-not (Test-Path $serviceLauncher)) {
    throw "Missing silent/background VBS launcher under $Root"
}

$startup = [Environment]::GetFolderPath("Startup")
$serviceStartupLink = Join-Path $startup "ETrade Pipeline Worker.lnk"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($serviceStartupLink)
$sc.TargetPath = "wscript.exe"
$sc.Arguments = "//B //Nologo `"$serviceLauncher`""
$sc.WorkingDirectory = $Root
$sc.WindowStyle = 7
$sc.Description = "Finance dual-PC pipeline worker (BOXONE) — no trading"
$sc.Save()
Write-Host "Startup: $serviceStartupLink"

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
New-Item -Path $runKey -Force | Out-Null
Set-ItemProperty -Path $runKey -Name "FinanceETradePipelineService" -Value "wscript.exe //B //Nologo `"$serviceLauncher`""
Write-Host "Run key: FinanceETradePipelineService"

# Remove any trading GUI autostart left behind
foreach ($name in @("FinanceETradeBackgroundService", "FinanceETradeShortBackgroundService")) {
    Remove-ItemProperty -Path $runKey -Name $name -ErrorAction SilentlyContinue
}
Remove-Item (Join-Path $startup "ETrade Background Service.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $startup "ETrade Trader.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $startup "ETrade Unified Trader.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $startup "ETrade Short Background Service.lnk") -Force -ErrorAction SilentlyContinue

# Logon scheduled task
$serviceTask = "Finance ETrade Pipeline Service"
try {
    Unregister-ScheduledTask -TaskName $serviceTask -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    Unregister-ScheduledTask -TaskName "Finance ETrade Background Service" -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$serviceLauncher`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask -TaskName $serviceTask -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "Scheduled task: $serviceTask"
} catch {
    Write-Host "Scheduled task note: $($_.Exception.Message)"
}

# Watchdog every 5 min
$watchdogTask = "Finance ETrade Worker Watchdog"
$ensureVbs = Join-Path $Root "Ensure ETrade Stack.vbs"
if (Test-Path $ensureVbs) {
    try {
        Unregister-ScheduledTask -TaskName $watchdogTask -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$ensureVbs`""
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) `
            -RepetitionDuration (New-TimeSpan -Days 9999)
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -Hidden
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $watchdogTask -Action $action -Trigger $trigger `
            -Settings $settings -Principal $principal -Force | Out-Null
        Write-Host "Watchdog task: $watchdogTask"
    } catch {
        Write-Host "Watchdog note: $($_.Exception.Message)"
    }
}

# Remove legacy trading-only tasks
foreach ($legacy in @(
        "Finance ETrade Worker",
        "Finance ETrade Live Trading",
        "Finance ETrade Day Trading"
    )) {
    Unregister-ScheduledTask -TaskName $legacy -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
}

# 6) Start pipeline worker now
Write-Host "Starting pipeline worker..."
Start-Process -FilePath "wscript.exe" -ArgumentList @("//B", "//Nologo", "`"$serviceLauncher`"") -WindowStyle Hidden

# 7) Smoke sync
try {
    & $py (Join-Path $Root "sync_shared_data.py") --push-pipeline
    Write-Host "Initial pipeline push attempted."
} catch {
    Write-Host "Sync note: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== Pipeline-only install done ==="
Write-Host "  role=pipeline  shared=$SharedRoot"
Write-Host "  Trading disabled on this host; AI-CODING owns E*TRADE orders."
Write-Host "  Log: $(Join-Path $Root 'output\etrade_worker.log')"
exit 0
