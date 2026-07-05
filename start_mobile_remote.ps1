# Start mobile monitor + Cloudflare tunnel for phone access from any network.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$venvPyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$monitor = Join-Path $root "mobile_monitor.py"
$cloudflared = Join-Path $root "tools\cloudflared.exe"
$configPath = Join-Path $root "etrade_config.json"

if (-not (Test-Path $venvPy)) {
    Write-Error "Run Install ETrade Trader.bat first."
}
if (-not (Test-Path $monitor)) {
    Write-Error "mobile_monitor.py not found."
}

& (Join-Path $root "install_mobile_tunnel.ps1") | Out-Host
if (-not (Test-Path $cloudflared)) {
    Write-Error "cloudflared.exe missing. Check internet and retry."
}

function Test-MonitorUp([int]$Port, [string]$Token) {
    try {
        $headers = @{ Authorization = "Bearer $Token" }
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -Headers $headers -TimeoutSec 3
        return $true
    } catch {
        return $false
    }
}

function Start-Monitor {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*mobile_monitor.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*mobile_monitor.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "Starting mobile monitor..."
    Start-Process -FilePath $venvPyw -ArgumentList "`"$monitor`"" -WorkingDirectory $root -WindowStyle Minimized
    Start-Sleep -Seconds 4
}

$port = 8766
$token = ""
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($config.mobile_monitor.port) { $port = [int]$config.mobile_monitor.port }
    if ($config.mobile_monitor.token) { $token = [string]$config.mobile_monitor.token }
}

if (-not $token) {
    Write-Host "Generating API token (one-time)..."
    $proc = Start-Process -FilePath $venvPy -ArgumentList "`"$monitor`"" -WorkingDirectory $root -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $token = [string]$config.mobile_monitor.token
}

if (-not (Test-MonitorUp $port $token)) {
    Start-Monitor
    if (-not (Test-MonitorUp $port $token)) {
        Write-Error "Mobile monitor did not start on port $port."
    }
}

$watchdog = Start-Job -ScriptBlock {
    param($Root, $VenvPyw, $Monitor, $Port, $Token)
    Set-Location $Root
    while ($true) {
        Start-Sleep -Seconds 30
        $up = $false
        try {
            $headers = @{ Authorization = "Bearer $Token" }
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -Headers $headers -TimeoutSec 3
            $up = $true
        } catch {
            $up = $false
        }
        if (-not $up) {
            Write-Output "[watchdog] Mobile monitor down - restarting..."
            Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -like "*mobile_monitor.py*" } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Start-Process -FilePath $VenvPyw -ArgumentList "`"$Monitor`"" -WorkingDirectory $Root -WindowStyle Minimized
            Start-Sleep -Seconds 4
        }
    }
} -ArgumentList $root, $venvPyw, $monitor, $port, $token

Write-Host ""
Write-Host "E*TRADE Trader - remote mobile monitor"
Write-Host "Keep this window open while using your phone."
Write-Host "Local port: $port"
if ($token) {
    Write-Host "Your token: $token"
} else {
    Write-Host "WARNING: No API token in etrade_config.json"
}
Write-Host ""
Write-Host "Starting Cloudflare tunnel..."
Write-Host ""

$tunnelReady = $false
$tunnelUrl = ""
$urlPattern = 'https://[a-z0-9-]+\.trycloudflare\.com'
$tunnelFile = Join-Path $root "output\mobile_tunnel_url.txt"

# cloudflared logs to stderr; do not treat that as a PowerShell failure.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $cloudflared tunnel --url "http://127.0.0.1:$port" 2>&1 | ForEach-Object {
        $line = $_.ToString()
        Write-Host $line
        if (-not $tunnelReady -and $line -match $urlPattern) {
            $tunnelUrl = $Matches[0]
            $tunnelReady = $true
            New-Item -ItemType Directory -Force -Path (Split-Path $tunnelFile) | Out-Null
            Set-Content -Path $tunnelFile -Value $tunnelUrl -Encoding ASCII
            Write-Host ""
            Write-Host "============================================================"
            Write-Host " OPEN ON YOUR PHONE (copy this full line):"
            if ($token) {
                Write-Host " $tunnelUrl/?token=$token"
            } else {
                Write-Host " $tunnelUrl"
            }
            Write-Host "============================================================"
            Write-Host ""
        }
    }
} finally {
    $ErrorActionPreference = $prevEap
    if ($watchdog) {
        Stop-Job $watchdog -ErrorAction SilentlyContinue
        Remove-Job $watchdog -Force -ErrorAction SilentlyContinue
    }
}

if (-not $tunnelReady) {
    Write-Error "Cloudflare tunnel did not start. Check internet connection and retry."
}

exit 0