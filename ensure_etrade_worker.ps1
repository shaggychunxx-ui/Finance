# Silent ensure — prefer VBS path (no PowerShell console when scheduled via wscript).
# Kept for manual runs and legacy task entries.
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ensureVbs = Join-Path $root "Ensure ETrade Stack.vbs"
$launcher = Join-Path $root "Start ETrade Background Service.vbs"
$watchdogLog = Join-Path $root "output\worker_watchdog.log"

function Write-WatchdogLog([string]$Message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try { Add-Content -Path $watchdogLog -Value "[$stamp] $Message" } catch {}
}

# Fast path: pure VBS (no extra windows when invoked correctly)
if (Test-Path $ensureVbs) {
    Start-Process -FilePath "wscript.exe" -ArgumentList @("//B", "//Nologo", "`"$ensureVbs`"") -WindowStyle Hidden -WorkingDirectory $root
    exit 0
}

if (Test-Path $launcher) {
    Start-Process -FilePath "wscript.exe" -ArgumentList @("//B", "//Nologo", "`"$launcher`"") -WindowStyle Hidden -WorkingDirectory $root
    Write-WatchdogLog "Ensure via Start VBS (fallback)"
    exit 0
}

Write-WatchdogLog "Ensure: no VBS launcher found"
exit 1
