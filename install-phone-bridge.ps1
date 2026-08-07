# install-phone-bridge.ps1
# Durable LAN phone bridge (port 8787) for E*TRADE Trader app.
# Run once on GROMIT:
#   powershell -ExecutionPolicy Bypass -File .\install-phone-bridge.ps1

$ErrorActionPreference = "Stop"
$taskName = "FinancePhoneBridge"
$repo = $PSScriptRoot
$live = if ($env:FINANCE_RUNTIME) { $env:FINANCE_RUNTIME } else { Join-Path $env:USERPROFILE "Finance" }
if (-not (Test-Path (Join-Path $live "phone_bridge.py"))) {
    $live = $repo
}

$pythonw = Join-Path $live ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($cmd) { $pythonw = $cmd.Source } else { $pythonw = "pythonw.exe" }
}
$bridge = Join-Path $live "phone_bridge.py"
if (-not (Test-Path $bridge)) { throw "Missing phone_bridge.py at $bridge" }

# Ensure script: start only if not already listening
$ensureDir = Join-Path $live "scripts"
if (-not (Test-Path $ensureDir)) { New-Item -ItemType Directory -Path $ensureDir -Force | Out-Null }
$ensurePs1 = Join-Path $ensureDir "Ensure-PhoneBridge.ps1"
@'
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
'@ | Set-Content -Path $ensurePs1 -Encoding UTF8

# Also drop copy next to git clone for discoverability
$repoEnsure = Join-Path $repo "Ensure-PhoneBridge.ps1"
Copy-Item $ensurePs1 $repoEnsure -Force

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ensurePs1`" -LiveRoot `"$live`"" `
    -WorkingDirectory $live

$triggers = @(
    (New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration (New-TimeSpan -Days 3650))
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -Hidden

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Ensure Finance phone_bridge.py listens on :8787 (GROMIT LAN)" `
    -Force | Out-Null

# Start now
& powershell -NoProfile -ExecutionPolicy Bypass -File $ensurePs1 -LiveRoot $live
$started = $LASTEXITCODE

Write-Host "Installed scheduled task: $taskName"
Write-Host "Live root: $live"
Write-Host "Ensure exit code: $started (0=listening or started ok)"
Write-Host "Health: http://127.0.0.1:8787/health"
