# Keep the headless E*TRADE worker running (watchdog for scheduled task / manual use).
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
$launcher = Join-Path $root "Start ETrade Background Service.vbs"
$watchdogLog = Join-Path $root "output\worker_watchdog.log"

function Write-WatchdogLog([string]$Message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $watchdogLog -Value "[$stamp] $Message"
}

if (-not (Test-Path $py)) {
    Write-WatchdogLog "Watchdog skipped - missing python venv"
    exit 1
}

$checkCmd = 'import etrade_worker; raise SystemExit(0 if etrade_worker.service_already_running() else 1)'
& $py -c $checkCmd | Out-Null
if ($LASTEXITCODE -eq 0) {
    exit 0
}

Write-WatchdogLog "Worker not running - restarting background service."
Remove-Item (Join-Path $root "output\etrade_worker.lock") -Force -ErrorAction SilentlyContinue

if (Test-Path $launcher) {
    Start-Process -FilePath "wscript.exe" -ArgumentList "`"$launcher`"" -WindowStyle Hidden -WorkingDirectory $root
} else {
    $script = Join-Path $root "etrade_worker.py"
    Start-Process -FilePath $py -ArgumentList "`"$script`" --service" -WindowStyle Hidden -WorkingDirectory $root
}

Start-Sleep -Seconds 4
& $py -c $checkCmd | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-WatchdogLog "Worker restart OK."
    exit 0
}

Write-WatchdogLog "Worker restart failed - check output\etrade_worker.log"
exit 1