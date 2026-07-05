# Fix phone home screen icon - use stable Wi-Fi URL (tunnel URLs expire and cause error 1033).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$monitor = Join-Path $root "mobile_monitor.py"
$configPath = Join-Path $root "etrade_config.json"
$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
$outputDir = Join-Path $root "output"
$homeFile = Join-Path $outputDir "mobile_homescreen_url.txt"
$remoteFile = Join-Path $outputDir "mobile_phone_url.txt"

function Get-MonitorConfig {
    $port = 8766
    $token = ""
    if (Test-Path $configPath) {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
        if ($config.mobile_monitor.port) { $port = [int]$config.mobile_monitor.port }
        if ($config.mobile_monitor.token) { $token = [string]$config.mobile_monitor.token }
    }
    return @{ Port = $port; Token = $token }
}

function Test-MonitorUp([int]$Port, [string]$Token) {
    try {
        $headers = @{ Authorization = "Bearer $Token" }
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -Headers $headers -TimeoutSec 4
        return $true
    } catch {
        return $false
    }
}

function Get-LanIp {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress)
    return [string]$ip
}

$cfg = Get-MonitorConfig
if (-not $cfg.Token) { Write-Error "Missing mobile_monitor.token in etrade_config.json" }

if (-not (Test-MonitorUp $cfg.Port $cfg.Token)) {
    if (-not (Test-Path $venvPyw)) { Write-Error "Run Install ETrade Trader.bat first." }
    Write-Host "Starting mobile monitor..."
    Start-Process -FilePath $venvPyw -ArgumentList "`"$monitor`"" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Seconds 4
    if (-not (Test-MonitorUp $cfg.Port $cfg.Token)) {
        Write-Error "Mobile monitor did not start."
    }
}

$lanIp = Get-LanIp
if (-not $lanIp) { Write-Error "No Wi-Fi IP found. Connect this PC to your router." }

$homeUrl = "http://${lanIp}:$($cfg.Port)/?token=$($cfg.Token)"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
Set-Content -Path $homeFile -Value $homeUrl -Encoding ASCII

Write-Host ""
Write-Host "============================================================"
Write-Host " STABLE HOME SCREEN URL (use this for Add to Home screen)"
Write-Host " $homeUrl"
Write-Host "============================================================"
Write-Host ""
Write-Host "Why: Cloudflare tunnel links change and cause error 1033."
Write-Host "This Wi-Fi link stays the same while you are at home."
if (Test-Path $remoteFile) {
    Write-Host ""
    Write-Host "Away from home / cellular: use the tunnel URL in:"
    Write-Host "  $remoteFile"
    Write-Host "  (open in browser - do not save tunnel links to home screen)"
}
Write-Host ""
Write-Host "On your phone:"
Write-Host "  1. DELETE the old E*TRADE home screen icon"
Write-Host "  2. Connect phone to the SAME Wi-Fi as this PC"
Write-Host "  3. Open the stable URL above in Chrome"
Write-Host "  4. Tap Install app or Add to Home screen"
Write-Host ""

if ($adb) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $devices = (& $adb devices 2>&1) | Select-Object -Skip 1 | Where-Object { $_ -match "`tdevice$" }
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if ($devices) {
        Write-Host "Opening stable URL on your phone..."
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $adb shell am start -a android.intent.action.VIEW -d $homeUrl 2>&1 | Out-Null
        } finally {
            $ErrorActionPreference = $prevEap
        }
        Write-Host "Opened on phone. Delete old icon, then Add to Home screen from this page."
    }
}

exit 0