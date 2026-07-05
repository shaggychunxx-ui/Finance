# Verify phone <-> desktop mobile monitor connection behavior.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$monitor = Join-Path $root "mobile_monitor.py"
$configPath = Join-Path $root "etrade_config.json"
$dashboard = Join-Path $root "mobile_dashboard.html"
$failures = @()

function Fail([string]$Message) {
    script:failures += $Message
    Write-Host "FAIL: $Message"
}

function Pass([string]$Message) {
    Write-Host "PASS: $Message"
}

if (-not (Test-Path $configPath)) { Fail "Missing etrade_config.json" }
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$port = [int]($config.mobile_monitor.port | ForEach-Object { if ($_) { $_ } else { 8766 } })
$token = [string]$config.mobile_monitor.token
if (-not $token) { Fail "Missing mobile_monitor.token" }

function Test-MonitorUp {
    try {
        $headers = @{ Authorization = "Bearer $token" }
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/status" -Headers $headers -TimeoutSec 4
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-MonitorUp)) {
    Write-Host "Starting mobile monitor for verification..."
    if (-not (Test-Path $venvPyw)) { Fail "Missing Python venv" }
    Start-Process -FilePath $venvPyw -ArgumentList "`"$monitor`"" -WorkingDirectory $root -WindowStyle Minimized
    Start-Sleep -Seconds 4
}

if (Test-MonitorUp) { Pass "Local monitor responds on port $port" } else { Fail "Local monitor not reachable on port $port" }

$html = Get-Content $dashboard -Raw
foreach ($needle in @("visibilitychange", "stopMonitoring", "startMonitoring", "scheduleReconnect")) {
    if ($html -like "*$needle*") { Pass "Dashboard contains $needle" } else { Fail "Dashboard missing $needle" }
}

try {
    $headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }
    $stop = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/automation/pause" -Method POST -Headers $headers -Body '{"paused":true}' -TimeoutSec 8
    if ($stop.automation.paused) { Pass "Stop all API works" } else { Fail "Stop all API did not pause automation" }
    $resume = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/automation/pause" -Method POST -Headers $headers -Body '{"paused":false}' -TimeoutSec 8
    if (-not $resume.automation.paused) { Pass "Resume all API works" } else { Fail "Resume all API did not resume automation" }
} catch {
    Fail "Automation API test failed: $_"
}

$gui = Get-Content (Join-Path $root "etrade_trader_gui.py") -Raw
if ($gui -like "*_sync_automation_from_config*") { Pass "Desktop syncs phone Stop/Resume changes" } else { Fail "Desktop missing phone automation sync" }

$tunnelFile = Join-Path $root "output\mobile_tunnel_url.txt"
if (Test-Path $tunnelFile) {
    $url = (Get-Content $tunnelFile -Raw).Trim()
    try {
        $null = Invoke-RestMethod -Uri "$url/api/status" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
        Pass "Remote tunnel reachable: $url"
    } catch {
        Write-Host "WARN: Remote tunnel not reachable (run Start Mobile Remote Access.bat): $url"
    }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "All checks passed."
    exit 0
}
Write-Host "$($failures.Count) check(s) failed."
exit 1