# Install mobile remote access to start at Windows login (hidden background).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $root "Start Mobile Remote Access.vbs"
$startup = [Environment]::GetFolderPath("Startup")
$startupLink = Join-Path $startup "Mobile Remote Access.lnk"
$taskName = "Finance ETrade Mobile Remote Access"
$iconDir = Join-Path $env:ProgramData "FinanceETrade"
$iconStable = Join-Path $iconDir "etrade_trader.ico"

if (-not (Test-Path $launcher)) {
    Write-Error "Missing $launcher"
}

if (Test-Path (Join-Path $root "etrade_trader.ico")) {
    New-Item -ItemType Directory -Force -Path $iconDir | Out-Null
    Copy-Item (Join-Path $root "etrade_trader.ico") $iconStable -Force
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($startupLink)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $root
$shortcut.Description = "E*TRADE Trader phone monitor tunnel (background)"
if (Test-Path $iconStable) { $shortcut.IconLocation = "$iconStable,0" }
$shortcut.Save()
Write-Host "Startup shortcut: $startupLink"

try {
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$launcher`""
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "Scheduled task (logon): $taskName"
} catch {
    Write-Host "Task Scheduler skipped ($($_.Exception.Message))."
}

Write-Host "Starting mobile remote access in background..."
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$launcher`"" -WindowStyle Hidden
Start-Sleep -Seconds 8

$phoneUrlFile = Join-Path $root "output\mobile_phone_url.txt"
if (Test-Path $phoneUrlFile) {
    Write-Host "Phone URL:"
    Get-Content $phoneUrlFile | Write-Host
} else {
    Write-Host "Phone URL will appear in output\mobile_phone_url.txt once the tunnel is ready."
}
Write-Host "Log: $(Join-Path $root 'output\mobile_remote_access.log')"