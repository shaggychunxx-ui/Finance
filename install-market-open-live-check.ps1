# install-market-open-live-check.ps1
# Scheduled check during US RTH so dead OAuth cannot go unnoticed at open.
# Run once on GROMIT:
#   powershell -ExecutionPolicy Bypass -File .\install-market-open-live-check.ps1

$ErrorActionPreference = "Stop"
$live = if ($env:FINANCE_RUNTIME) { $env:FINANCE_RUNTIME } else { Join-Path $env:USERPROFILE "Finance" }
$script = Join-Path $live "check_market_open_live.py"
if (-not (Test-Path $script)) { throw "Missing $script" }

$py = Join-Path $live ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source } else { $py = "python.exe" }
}

$taskName = "FinanceMarketOpenLiveCheck"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute $py `
    -Argument "`"$script`"" `
    -WorkingDirectory $live

# Every 15 minutes; script no-ops outside RTH
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -Hidden

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "During US RTH: verify E*TRADE LIVE STATUS OK; write LIVE_BLOCKER.txt if not" `
    -Force | Out-Null

Write-Host "Installed $taskName (every 15 min; RTH gate inside script)"
Write-Host "Manual: $py $script"
Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
