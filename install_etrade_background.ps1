$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$iconDir = Join-Path $env:ProgramData "FinanceETrade"
$iconStable = Join-Path $iconDir "etrade_trader.ico"
$serviceLauncher = Join-Path $root "Start ETrade Background Service.vbs"
$guiExe = Join-Path $root "ETrade Trader.exe"
$guiLauncher = Join-Path $root ".venv\Scripts\pythonw.exe"
$guiArgs = Join-Path $root "launch_etrade_trader.py"
$scheduledLauncher = Join-Path $root "Scheduled ETrade Worker Run.vbs"
$liveTradingLauncher = Join-Path $root "Scheduled ETrade Live Trading.vbs"
$dayTradingLauncher = Join-Path $root "Scheduled ETrade Day Trading.vbs"
$serviceTask = "Finance ETrade Background Service"
$watchdogTask = "Finance ETrade Worker Watchdog"
$watchdogScript = Join-Path $root "ensure_etrade_worker.ps1"
$watchdogBat = Join-Path $root "Run ETrade Worker Watchdog.bat"
$scheduledTask = "Finance ETrade Worker"
$liveTradingTask = "Finance ETrade Live Trading"
$dayTradingTask = "Finance ETrade Day Trading"
$startup = [Environment]::GetFolderPath("Startup")
$serviceStartupLink = Join-Path $startup "ETrade Background Service.lnk"
$guiStartupLink = Join-Path $startup "ETrade Trader.lnk"

if (-not (Test-Path $serviceLauncher)) {
    Write-Error "Missing $serviceLauncher"
    exit 1
}

if (Test-Path (Join-Path $root "etrade_trader.ico")) {
    New-Item -ItemType Directory -Force -Path $iconDir | Out-Null
    Copy-Item (Join-Path $root "etrade_trader.ico") $iconStable -Force
}

function Install-StartupShortcut {
    param(
        [string]$LinkPath,
        [string]$TargetPath,
        [string]$Arguments = "",
        [string]$Description
    )
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($LinkPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = $Description
    if (Test-Path $iconStable) { $shortcut.IconLocation = "$iconStable,0" }
    elseif (Test-Path (Join-Path $root "app_icon.ico")) {
        $shortcut.IconLocation = "$(Join-Path $root 'app_icon.ico'),0"
    }
    $shortcut.Save()
    Write-Host "Startup shortcut: $LinkPath"
}

$runKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$serviceRunCommand = "wscript.exe `"$serviceLauncher`""

function Install-RunKeyStartup {
    param(
        [string]$Name,
        [string]$Command
    )
    New-Item -Path $runKeyPath -Force | Out-Null
    Set-ItemProperty -Path $runKeyPath -Name $Name -Value $Command
    Write-Host "Run key (logon): $Name"
}

$taskOk = $false
try {
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$serviceLauncher`""
    Unregister-ScheduledTask -TaskName $serviceTask -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    Register-ScheduledTask -TaskName $serviceTask -Action $action -Trigger $trigger -Force -ErrorAction Stop | Out-Null
    $taskOk = $true
    Write-Host "Scheduled task (logon): $serviceTask"
} catch {
    Write-Host "Task Scheduler logon task skipped ($($_.Exception.Message))."
    try {
        schtasks /Create /F /TN $serviceTask /TR $serviceRunCommand /SC ONLOGON /RL LIMITED 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $taskOk = $true
            Write-Host "Scheduled task (schtasks logon): $serviceTask"
        }
    } catch {
        Write-Host "schtasks logon task skipped ($($_.Exception.Message))."
    }
}

try {
    Install-RunKeyStartup -Name "FinanceETradeBackgroundService" -Command $serviceRunCommand
} catch {
    Write-Host "Run key install skipped ($($_.Exception.Message))."
}

Install-StartupShortcut -LinkPath $serviceStartupLink -TargetPath $serviceLauncher `
    -Description "Finance E*TRADE background trading worker"

if (Test-Path $guiExe) {
    Install-StartupShortcut -LinkPath $guiStartupLink -TargetPath $guiExe `
        -Description "Finance E*TRADE Trader desktop app"
    $programsLink = Join-Path ([Environment]::GetFolderPath("Programs")) "ETrade Trader.lnk"
    Install-StartupShortcut -LinkPath $programsLink -TargetPath $guiExe `
        -Description "Finance agent strategies applied to E*TRADE account"
} elseif (Test-Path $guiLauncher) {
    Install-StartupShortcut -LinkPath $guiStartupLink -TargetPath $guiLauncher `
        -Arguments "`"$guiArgs`"" -Description "Finance E*TRADE Trader desktop app"
    $programsLink = Join-Path ([Environment]::GetFolderPath("Programs")) "ETrade Trader.lnk"
    Install-StartupShortcut -LinkPath $programsLink -TargetPath $guiLauncher `
        -Arguments "`"$guiArgs`"" -Description "Finance agent strategies applied to E*TRADE account"
}

$watchdogOk = $false
if (Test-Path $watchdogScript) {
    $watchCmd = "`"$watchdogBat`""
    try {
        Unregister-ScheduledTask -TaskName $watchdogTask -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    } catch {}
    schtasks /Create /F /TN $watchdogTask /TR $watchCmd /SC MINUTE /MO 5 /RL LIMITED 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $watchdogOk = $true
        Write-Host "Scheduled task (every 5 min): $watchdogTask"
    } else {
        Write-Host "Watchdog task skipped (schtasks exit $LASTEXITCODE)."
    }
}

# Remove legacy duplicate tasks — the logon service loop handles all automation.
foreach ($legacyTask in @($scheduledTask, $liveTradingTask, $dayTradingTask)) {
    try {
        Unregister-ScheduledTask -TaskName $legacyTask -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        Write-Host "Removed duplicate task: $legacyTask (service loop handles this now)"
    } catch {
        Write-Host "Could not remove $legacyTask : $($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "Startup installed."
Write-Host "  Background worker autostart: Startup folder + Run key$(if ($taskOk) { ' + Scheduled task' } else { '' })$(if ($watchdogOk) { ' + 5-min watchdog' } else { '' })"
Write-Host "  Background worker: agents every 5 min, plan every 30 min, live trading every 15 min"
Write-Host "  GUI app: opens automatically at Windows login"
Write-Host "  Log: $(Join-Path $root 'output\etrade_worker.log')"
Write-Host ""
Write-Host "Confirm your account once in the GUI - it is saved across restarts."
Write-Host ""
Write-Host "Starting background service now..."
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$serviceLauncher`"" -WindowStyle Hidden

$mobileRemoteInstaller = Join-Path $root "install_mobile_remote_background.ps1"
if (Test-Path $mobileRemoteInstaller) {
    Write-Host ""
    Write-Host "Installing mobile remote access (phone monitor tunnel)..."
    & $mobileRemoteInstaller | Out-Host
}

if ($taskOk) {
    Get-ScheduledTask -TaskName $serviceTask -ErrorAction SilentlyContinue | Select-Object TaskName, State
}