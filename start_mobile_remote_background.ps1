# Keep mobile monitor + Cloudflare tunnel running in the background.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$venvPyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$monitor = Join-Path $root "mobile_monitor.py"
$cloudflared = Join-Path $root "tools\cloudflared.exe"
$configPath = Join-Path $root "etrade_config.json"
$outputDir = Join-Path $root "output"
$logFile = Join-Path $outputDir "mobile_remote_access.log"
$cloudLog = Join-Path $outputDir "cloudflared.log"
$tunnelFile = Join-Path $outputDir "mobile_tunnel_url.txt"
$phoneUrlFile = Join-Path $outputDir "mobile_phone_url.txt"
$homeUrlFile = Join-Path $outputDir "mobile_homescreen_url.txt"
$lockFile = Join-Path $outputDir "mobile_remote_access.lock"
$urlPattern = 'https://[a-z0-9-]+\.trycloudflare\.com'

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $logFile -Value $line -Encoding ASCII
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

function Start-MonitorService([int]$Port, [string]$Token) {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*mobile_monitor.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Process -FilePath $venvPyw -ArgumentList "`"$monitor`"" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Seconds 4
    return (Test-MonitorUp $Port $Token)
}

function Get-CloudflaredForPort([int]$Port) {
    Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*127.0.0.1:$Port*" }
}

function Start-CloudflaredService([int]$Port) {
    $existing = Get-CloudflaredForPort $Port
    if ($existing) { return $true }
    if (-not (Test-Path $cloudflared)) {
        & (Join-Path $root "install_mobile_tunnel.ps1") | Out-Null
    }
    if (-not (Test-Path $cloudflared)) {
        Write-Log "cloudflared.exe missing"
        return $false
    }
    Remove-Item $cloudLog -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath $cloudflared -ArgumentList "tunnel --url http://127.0.0.1:$Port" `
        -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardError $cloudLog | Out-Null
    Start-Sleep -Seconds 6
    return [bool](Get-CloudflaredForPort $Port)
}

function Get-TunnelUrl {
    if (-not (Test-Path $cloudLog)) { return "" }
    $match = Select-String -Path $cloudLog -Pattern $urlPattern -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($match) { return $match.Matches[0].Value }
    return ""
}

function Save-PhoneUrl([string]$TunnelUrl, [string]$Token) {
    if (-not $TunnelUrl) { return }
    Set-Content -Path $tunnelFile -Value $TunnelUrl -Encoding ASCII
    if ($Token) {
        Set-Content -Path $phoneUrlFile -Value "$TunnelUrl/?token=$Token" -Encoding ASCII
    } else {
        Set-Content -Path $phoneUrlFile -Value $TunnelUrl -Encoding ASCII
    }
}

function Test-TunnelUp([string]$TunnelUrl, [string]$Token) {
    if (-not $TunnelUrl) { return $false }
    try {
        $headers = @{ Authorization = "Bearer $Token" }
        $null = Invoke-RestMethod -Uri "$TunnelUrl/api/status" -Headers $headers -TimeoutSec 12
        return $true
    } catch {
        return $false
    }
}

function Restart-CloudflaredService([int]$Port) {
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    return (Start-CloudflaredService $Port)
}

function Test-AnotherInstance {
    if (-not (Test-Path $lockFile)) { return $false }
    $lockedPid = 0
    [void][int]::TryParse((Get-Content $lockFile -Raw).Trim(), [ref]$lockedPid)
    if ($lockedPid -le 0) { return $false }
    $proc = Get-Process -Id $lockedPid -ErrorAction SilentlyContinue
    return [bool]$proc
}

if (-not (Test-Path $venvPy)) {
    Write-Log "Install ETrade Trader.bat required."
    exit 1
}

if (Test-AnotherInstance) {
    Write-Log "Already running (pid $(Get-Content $lockFile -Raw).)"
    exit 0
}

Set-Content -Path $lockFile -Value $PID -Encoding ASCII
Write-Log "Mobile remote access service started (pid $PID)."

try {
    & (Join-Path $root "install_mobile_tunnel.ps1") | Out-Null
} catch {
    Write-Log "cloudflared install warning: $($_.Exception.Message)"
}

$port = 8766
$token = ""
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($config.mobile_monitor.port) { $port = [int]$config.mobile_monitor.port }
    if ($config.mobile_monitor.token) { $token = [string]$config.mobile_monitor.token }
}

if (-not $token) {
    $proc = Start-Process -FilePath $venvPy -ArgumentList "`"$monitor`"" -WorkingDirectory $root -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $token = [string]$config.mobile_monitor.token
}

$lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress)
if ($lanIp -and $token) {
    Set-Content -Path $homeUrlFile -Value "http://${lanIp}:$port/?token=$token" -Encoding ASCII
}

$lastUrl = ""
while ($true) {
    try {
        if (-not (Test-MonitorUp $port $token)) {
            if (Start-MonitorService $port $token) {
                Write-Log "Mobile monitor restarted on port $port."
            } else {
                Write-Log "Mobile monitor failed to start on port $port."
            }
        }

        if (-not (Get-CloudflaredForPort $port)) {
            if (Start-CloudflaredService $port) {
                Write-Log "Cloudflare tunnel restarted."
                $lastUrl = ""
            } else {
                Write-Log "Cloudflare tunnel failed to start."
            }
        }

        $tunnelUrl = Get-TunnelUrl
        if ($tunnelUrl -and -not (Test-TunnelUp $tunnelUrl $token)) {
            Write-Log "Tunnel URL stale - restarting cloudflared."
            if (Restart-CloudflaredService $port) { $lastUrl = "" }
            $tunnelUrl = Get-TunnelUrl
        }

        if ($tunnelUrl -and $tunnelUrl -ne $lastUrl) {
            $lastUrl = $tunnelUrl
            Save-PhoneUrl $tunnelUrl $token
            Write-Log "Phone URL updated: $tunnelUrl"
        }
    } catch {
        Write-Log "Loop error: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 15
}