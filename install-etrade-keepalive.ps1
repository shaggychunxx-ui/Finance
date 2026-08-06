# install-etrade-keepalive.ps1 — keep E*TRADE session alive all RTH day
# powershell -ExecutionPolicy Bypass -File .\install-etrade-keepalive.ps1

$ErrorActionPreference = "Stop"
$live = if ($env:FINANCE_RUNTIME) { $env:FINANCE_RUNTIME } else { Join-Path $env:USERPROFILE "Finance" }
$script = Join-Path $live "etrade_keepalive.py"
if (-not (Test-Path $script)) { throw "Missing $script" }

$py = Join-Path $live ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source } else { $py = "python.exe" }
}

$taskName = "FinanceEtradeKeepAlive"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $live
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Every 10 min: probe E*TRADE list-accounts to prevent 2h idle disconnect" `
    -Force | Out-Null

Write-Host "Installed $taskName (every 10 minutes)"
Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
& $py $script
