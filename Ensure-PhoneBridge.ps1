param(
    [string]$LiveRoot = $env:USERPROFILE + "\Finance",
    [int]$Port = 8787
)
$ErrorActionPreference = "Continue"
if ($env:FINANCE_RUNTIME) { $LiveRoot = $env:FINANCE_RUNTIME }
$bridge = Join-Path $LiveRoot "phone_bridge.py"
if (-not (Test-Path $bridge)) { exit 1 }

function Test-PortListen([int]$p) {
    try {
        $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        return ($null -ne $c)
    } catch { return $false }
}
if (Test-PortListen $Port) { exit 0 }

$pythonw = Join-Path $LiveRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($cmd) { $pythonw = $cmd.Source } else { $pythonw = "pythonw.exe" }
}
Start-Process -FilePath $pythonw -ArgumentList "`"$bridge`"" -WorkingDirectory $LiveRoot -WindowStyle Hidden
Start-Sleep -Seconds 2
if (Test-PortListen $Port) { exit 0 } else { exit 2 }
