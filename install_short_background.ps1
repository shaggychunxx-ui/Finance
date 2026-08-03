# Retire standalone short_worker background service (do not reinstall).
# Main headless stack: finance_supervisor + continuum + etrade_worker.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$Lnk = Join-Path $Startup "ETrade Short Background Service.lnk"
$RunName = "FinanceETradeShortBackgroundService"
$TaskName = "Finance ETrade Short Dry-Run"

Write-Host "Retiring standalone Short background service..."

# Stop running short_worker processes
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'short_worker\.py') } |
    ForEach-Object {
        Write-Host "  Stopping PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# Remove autostart surfaces
if (Test-Path $Lnk) {
    Remove-Item $Lnk -Force
    Write-Host "  Removed Startup: $Lnk"
}
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Remove-ItemProperty -Path $runKey -Name $RunName -ErrorAction SilentlyContinue
Write-Host "  Cleared Run key: $RunName (if present)"

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Host "  Disabled scheduled task: $TaskName"
} catch {
    Write-Host "  Scheduled task $TaskName not found or already gone"
}

# Keep VBS as a no-op so any leftover shortcut is harmless
$Vbs = Join-Path $Root "Start ETrade Short Background Service.vbs"
$VbsContent = @'
' Standalone short_worker --service is RETIRED.
' Use the main Finance stack instead:
'   Start ETrade Background Service.vbs
'   or Start Silent Worker Only.vbs
Option Explicit
WScript.Quit 0
'@
Set-Content -Path $Vbs -Value $VbsContent -Encoding ASCII
Write-Host "  VBS is no-op: $Vbs"

Write-Host ""
Write-Host "Done. Use main worker only:"
Write-Host "  Start Silent Worker Only.vbs"
Write-Host "  or Install ETrade Background.bat"
Write-Host "Manual short tools remain: short_worker.py --plan / --day / --force-dry-run"
