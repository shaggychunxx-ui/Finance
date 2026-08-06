# install-etrade-live-watchdog.ps1
# Every 1 minute during the day: if RTH and E*TRADE not live → diagnose/repair/open OAuth.
# powershell -ExecutionPolicy Bypass -File .\install-etrade-live-watchdog.ps1

$ErrorActionPreference = "Stop"
$live = if ($env:FINANCE_RUNTIME) { $env:FINANCE_RUNTIME } else { Join-Path $env:USERPROFILE "Finance" }
$script = Join-Path $live "etrade_live_watchdog.py"
if (-not (Test-Path $script)) { throw "Missing $script" }

$py = Join-Path $live ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) {
    $py = Join-Path $live ".venv\Scripts\python.exe"
}
if (-not (Test-Path $py)) { $py = "pythonw.exe" }

$taskName = "FinanceEtradeLiveWatchdog"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $live
# Every 1 minute
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -Hidden `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "RTH: every 1 min verify E*TRADE live; auto-repair; open OAuth if dead" `
    -Force | Out-Null

Write-Host "Installed $taskName (every 1 minute; RTH logic inside script)"
Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
& (Join-Path $live ".venv\Scripts\python.exe") $script
