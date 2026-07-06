# Install E*TRADE Trader as a standalone phone app (HTTPS PWA — no Chrome browser UI).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$venvPyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$monitor = Join-Path $root "mobile_monitor.py"
$configPath = Join-Path $root "etrade_config.json"
$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
$outputDir = Join-Path $root "output"
$homeFile = Join-Path $outputDir "mobile_homescreen_url.txt"
$remoteFile = Join-Path $outputDir "mobile_phone_url.txt"

function Get-MonitorConfig {
    $port = 8766
    $httpsPort = 8767
    $pwaHttps = $true
    $token = ""
    if (Test-Path $configPath) {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
        if ($config.mobile_monitor.port) { $port = [int]$config.mobile_monitor.port }
        if ($config.mobile_monitor.https_port) { $httpsPort = [int]$config.mobile_monitor.https_port }
        if ($null -ne $config.mobile_monitor.pwa_https) { $pwaHttps = [bool]$config.mobile_monitor.pwa_https }
        if ($config.mobile_monitor.token) { $token = [string]$config.mobile_monitor.token }
    }
    return @{ Port = $port; HttpsPort = $httpsPort; PwaHttps = $pwaHttps; Token = $token }
}

function Test-MonitorHttp([int]$Port, [string]$Token) {
    try {
        $headers = @{ Authorization = "Bearer $Token" }
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -Headers $headers -TimeoutSec 4
        return $true
    } catch {
        return $false
    }
}

function Test-MonitorHttps([int]$Port, [string]$Token) {
    $escaped = $Token.Replace("'", "''")
    $py = @"
import json, ssl, urllib.request
ctx = ssl._create_unverified_context()
req = urllib.request.Request(
    'https://127.0.0.1:$Port/api/status?token=$escaped',
    headers={'Authorization': 'Bearer $escaped'},
)
with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
    json.load(resp)
print('ok')
"@
    for ($i = 0; $i -lt 6; $i++) {
        try {
            $out = & $venvPy -c $py 2>$null
            if ($out -match "ok") { return $true }
        } catch {
            # HTTPS listener may still be starting
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Restart-Monitor {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*mobile_monitor.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*mobile_monitor.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (-not (Test-Path $venvPyw)) { Write-Error "Run Install ETrade Trader.bat first." }
    Write-Host "Starting mobile monitor (HTTP + HTTPS for phone app)..."
    Start-Process -FilePath $venvPyw -ArgumentList "`"$monitor`"" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

function Get-LanIp {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress)
    return [string]$ip
}

function Ensure-TlsMaterial {
    & $venvPy -c "from app_paths import OUTPUT; from mobile_tls import ensure_tls_material; ensure_tls_material(OUTPUT / 'mobile_tls'); print('tls ready')" | Out-Host
}

function Install-PhoneCa {
    param([string]$AdbPath)
    $caFile = Join-Path $outputDir "mobile_root_ca.crt"
    if (-not (Test-Path $caFile)) { return $false }
    $remote = "/sdcard/Download/etrade_mobile_ca.crt"
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $AdbPath push $caFile $remote 2>&1 | Out-Null
        & $AdbPath shell am start -a android.credentials.INSTALL -t application/x-x509-ca-cert -d "file://$remote" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            & $AdbPath shell am start -a android.intent.action.VIEW -d "file://$remote" -t application/x-x509-ca-cert 2>&1 | Out-Null
        }
    } finally {
        $ErrorActionPreference = $prevEap
    }
    return $true
}

if (-not (Test-Path $venvPy)) {
    Write-Error "Run Install ETrade Trader.bat first."
}

& $venvPy -m pip install cryptography -q | Out-Null
& $venvPy (Join-Path $root "generate_mobile_icons.py") | Out-Host
Ensure-TlsMaterial

$cfg = Get-MonitorConfig
if (-not $cfg.Token) { Write-Error "Missing mobile_monitor.token in etrade_config.json" }

$needsRestart = -not (Test-MonitorHttp $cfg.Port $cfg.Token)
if ($cfg.PwaHttps) {
    $needsRestart = $needsRestart -or -not (Test-MonitorHttps $cfg.HttpsPort $cfg.Token)
}
if ($needsRestart) {
    Restart-Monitor
    if (-not (Test-MonitorHttp $cfg.Port $cfg.Token)) {
        Write-Error "Mobile monitor did not start on port $($cfg.Port)."
    }
    if ($cfg.PwaHttps -and -not (Test-MonitorHttps $cfg.HttpsPort $cfg.Token)) {
        Write-Error "HTTPS phone app port $($cfg.HttpsPort) is not reachable. Allow it in Windows Firewall if prompted."
    }
}

$lanIp = Get-LanIp
if (-not $lanIp) { Write-Error "No Wi-Fi IP found. Connect this PC to your router." }

$appPort = if ($cfg.PwaHttps) { $cfg.HttpsPort } else { $cfg.Port }
$scheme = if ($cfg.PwaHttps) { "https" } else { "http" }
$homeUrl = "${scheme}://${lanIp}:${appPort}/?source=pwa&token=$($cfg.Token)"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
Set-Content -Path $homeFile -Value $homeUrl -Encoding ASCII

Write-Host ""
Write-Host "============================================================"
Write-Host " PHONE APP INSTALL URL (standalone - no Chrome browser)"
Write-Host " $homeUrl"
Write-Host "============================================================"
Write-Host ""
Write-Host "Steps on your phone:"
Write-Host "  1. DELETE any old E*TRADE home screen icon"
Write-Host "  2. Connect phone to the SAME Wi-Fi as this PC"
if ($cfg.PwaHttps) {
    Write-Host "  3. Install the security certificate when prompted (name it ETrade Trader)"
    Write-Host "  4. Open the URL above in Chrome"
    Write-Host "  5. Tap Install app on the page (or Chrome menu -> Install app)"
} else {
    Write-Host "  3. Open the URL above in Chrome"
    Write-Host "  4. Tap Install app on the page (or Chrome menu -> Install app)"
}
Write-Host "  6. Open the new icon - it runs full screen as its own app"
Write-Host ""
Write-Host "Why HTTPS: Android only installs real apps (no browser bars) over HTTPS."
Write-Host "Tunnel links still change - do not save trycloudflare.com to home screen."
if (Test-Path $remoteFile) {
    Write-Host ""
    Write-Host "Away from home: open the tunnel URL in $remoteFile in browser only."
}
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
        if ($cfg.PwaHttps -and (Install-PhoneCa $adb)) {
            Write-Host ""
            Write-Host "On your phone: install the certificate (name: ETrade Trader)."
            Start-Sleep -Seconds 8
        }
        Write-Host "Opening install URL on your phone..."
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $adb shell am start -a android.intent.action.VIEW -d $homeUrl 2>&1 | Out-Null
        } finally {
            $ErrorActionPreference = $prevEap
        }
        Write-Host "Opened on phone. Tap Install app on the page or in the Chrome menu."
    }
}

exit 0