# Stop background mobile remote access service.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$lockFile = Join-Path $root "output\mobile_remote_access.lock"
$logFile = Join-Path $root "output\mobile_remote_access.log"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $logFile -Value $line -Encoding ASCII
}

if (Test-Path $lockFile) {
    $lockedPid = 0
    [void][int]::TryParse((Get-Content $lockFile -Raw).Trim(), [ref]$lockedPid)
    if ($lockedPid -gt 0) {
        Stop-Process -Id $lockedPid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*start_mobile_remote_background.ps1*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Log "Mobile remote access service stopped."
Write-Host "Mobile remote access stopped."