# Install/open E*TRADE Trader mobile monitor on a connected Android phone.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$venvPyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$monitor = Join-Path $root "mobile_monitor.py"
$cloudflared = Join-Path $root "tools\cloudflared.exe"
$configPath = Join-Path $root "etrade_config.json"
$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source

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
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -Headers $headers -TimeoutSec 3
        return $true
    } catch {
        return $false
    }
}

function Start-Monitor([int]$Port, [string]$Token) {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*mobile_monitor.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*mobile_monitor.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (-not (Test-Path $venvPyw)) { Write-Error "Run Install ETrade Trader.bat first." }
    Write-Host "Starting mobile monitor..."
    Start-Process -FilePath $venvPyw -ArgumentList "`"$monitor`"" -WorkingDirectory $root -WindowStyle Minimized
    Start-Sleep -Seconds 4
    if (-not (Test-MonitorUp $Port $Token)) {
        Write-Error "Mobile monitor did not start on port $Port."
    }
}

function Ensure-Monitor([int]$Port, [string]$Token) {
    if (Test-MonitorUp $Port $Token) { return }
    Start-Monitor $Port $Token
}

function Get-LanIp {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress)
    return [string]$ip
}

function Get-SavedTunnelUrl {
    $tunnelFile = Join-Path $root "output\mobile_tunnel_url.txt"
    if (Test-Path $tunnelFile) {
        return (Get-Content $tunnelFile -Raw).Trim()
    }
    return ""
}

function Test-TunnelUp([string]$Url, [string]$Token) {
    if (-not $Url) { return $false }
    try {
        $headers = @{ Authorization = "Bearer $Token" }
        $null = Invoke-RestMethod -Uri "$Url/api/status" -Headers $headers -TimeoutSec 12
        return $true
    } catch {
        return $false
    }
}

function Start-TunnelIfNeeded([int]$Port, [string]$Token) {
    $running = Get-Process cloudflared -ErrorAction SilentlyContinue
    if ($running) {
        $saved = Get-SavedTunnelUrl
        if ($saved -and (Test-TunnelUp $saved $Token)) {
            Write-Host "Cloudflare tunnel already running: $saved"
            return @{ Process = $null; Url = $saved }
        }
        Write-Host "Restarting Cloudflare tunnel..."
        $running | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    if (-not (Test-Path $cloudflared)) {
        & (Join-Path $root "install_mobile_tunnel.ps1") | Out-Host
    }
    Write-Host "Starting Cloudflare tunnel for cellular/remote access..."
    $logFile = Join-Path $root "output\cloudflared.log"
    New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null
    Remove-Item $logFile -Force -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $cloudflared -ArgumentList "tunnel --url http://127.0.0.1:$Port" `
        -WorkingDirectory $root -PassThru -RedirectStandardError $logFile -WindowStyle Hidden
    $urlPattern = 'https://[a-z0-9-]+\.trycloudflare\.com'
    $deadline = (Get-Date).AddSeconds(30)
    $tunnelUrl = ""
    while ((Get-Date) -lt $deadline -and -not $tunnelUrl) {
        Start-Sleep -Milliseconds 500
        if (Test-Path $logFile) {
            $match = Select-String -Path $logFile -Pattern $urlPattern | Select-Object -First 1
            if ($match) { $tunnelUrl = $match.Matches[0].Value }
        }
    }
    if (-not $tunnelUrl) {
        if ($proc -and -not $proc.HasExited) { $proc | Stop-Process -Force -ErrorAction SilentlyContinue }
        Write-Error "Could not get Cloudflare tunnel URL. Run Start Mobile Remote Access.bat manually."
    }
    Start-Sleep -Seconds 3
    if (-not (Test-TunnelUp $tunnelUrl $Token)) {
        if ($proc -and -not $proc.HasExited) { $proc | Stop-Process -Force -ErrorAction SilentlyContinue }
        Write-Error "Tunnel started but phone URL is not reachable yet. Check monitor and retry."
    }
    $tunnelFile = Join-Path $root "output\mobile_tunnel_url.txt"
    Set-Content -Path $tunnelFile -Value $tunnelUrl -Encoding ASCII
    Write-Host "Tunnel ready: $tunnelUrl"
    return @{ Process = $proc; Url = $tunnelUrl }
}

function Open-OnPhone([string]$Url) {
    if (-not $adb) {
        Write-Host "ADB not found. Open this URL on your phone manually:"
        Write-Host $Url
        return $false
    }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $devices = (& $adb devices 2>&1) | Select-Object -Skip 1 | Where-Object { $_ -match "`tdevice$" }
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if (-not $devices) {
        Write-Host "No phone detected over USB."
        Write-Host "Enable USB debugging, connect the cable, tap Allow on the phone, then run again."
        Write-Host "Or open this URL on your phone:"
        Write-Host $Url
        return $false
    }
    Write-Host "Opening monitor on your phone..."
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $adb shell am start -a android.intent.action.VIEW -d $Url 2>&1 | Out-Null
    } finally {
        $ErrorActionPreference = $prevEap
    }
    return $true
}

if (-not (Test-Path $venvPy)) {
    Write-Error "Run Install ETrade Trader.bat first."
}

& $venvPy (Join-Path $root "generate_mobile_icons.py") | Out-Host

$cfg = Get-MonitorConfig
Ensure-Monitor $cfg.Port $cfg.Token

$lanIp = Get-LanIp
$lanUrl = ""
if ($lanIp -and $cfg.Token) {
    $lanUrl = "http://${lanIp}:$($cfg.Port)/?token=$($cfg.Token)"
}

$tunnel = Start-TunnelIfNeeded $cfg.Port $cfg.Token
$phoneUrl = ""
if ($tunnel -and $tunnel.Url -and $cfg.Token) {
    $phoneUrl = "$($tunnel.Url)/?token=$($cfg.Token)"
} elseif ($lanUrl) {
    $phoneUrl = $lanUrl
}

if (-not $phoneUrl) {
    Write-Error "Could not build phone URL."
}

Write-Host ""
Write-Host "============================================================"
Write-Host " PHONE MONITOR URL"
Write-Host " $phoneUrl"
Write-Host "============================================================"
Write-Host ""

$opened = Open-OnPhone $phoneUrl
if ($opened) {
    Write-Host "Monitor opened on your phone."
    Write-Host ""
    Write-Host "INSTALL AS PHONE APP (no Chrome browser):"
    Write-Host "  Run Install Phone App.bat while phone is on same Wi-Fi."
    Write-Host "  Do NOT add trycloudflare.com links to your home screen."
    Write-Host ""
    Write-Host "Temporary remote open (cellular):"
    Write-Host "  Use the tunnel URL in browser only - it changes when tunnel restarts."
} else {
    Write-Host "Copy the URL above into your phone browser."
}

if ($tunnel -and $tunnel.Process) {
    Write-Host ""
    Write-Host "Keep this window open while using cellular/remote access."
    Write-Host "Press Ctrl+C to stop the tunnel."
    try {
        while (-not $tunnel.Process.HasExited) {
            Start-Sleep -Seconds 2
        }
    } finally {
        if (-not $tunnel.Process.HasExited) {
            $tunnel.Process.Kill()
        }
    }
}

exit 0