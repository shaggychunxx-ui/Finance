# Rebuild icon and refresh desktop, Start Menu, and taskbar shortcuts.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$iconDir = Join-Path $env:ProgramData "FinanceETrade"
$iconName = "etrade_trader.ico"
$iconSource = Join-Path $root $iconName
$iconStable = Join-Path $iconDir $iconName
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$gui = Join-Path $root "launch_etrade_trader.py"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$serviceLauncher = Join-Path $root "Start ETrade Background Service.vbs"
$agentsLauncher = Join-Path $root "Launch Finance Agents.vbs"
$launcherExe = Join-Path $root "ETrade Trader.exe"
$appId = "Finance.ETrade.Trader.1"
$setAppIdScript = Join-Path $root "set_shortcut_appid.ps1"

if (-not (Test-Path $venvPy)) {
    Write-Error "Run Install ETrade Trader.bat first - Python venv is missing."
}

& $venvPy (Join-Path $root "create_app_icon.py") | Out-Host
if (-not (Test-Path $iconSource)) {
    Write-Error "Icon build failed - $iconName not found."
}

if (-not (Test-Path $launcherExe)) {
    Write-Host "Building branded launcher exe for taskbar icon..."
    & $venvPy (Join-Path $root "build_etrade_launcher.py")
}

New-Item -ItemType Directory -Force -Path $iconDir | Out-Null
Copy-Item $iconSource $iconStable -Force

if (Test-Path $launcherExe) {
    $launchTarget = $launcherExe
    $launchArgs = ""
    Write-Host "Using launcher: $launcherExe"
} else {
    $launchTarget = $pyw
    $launchArgs = "`"$gui`""
    Write-Host "Launcher exe not built - using pythonw with AppUserModelID."
}

$shell = New-Object -ComObject WScript.Shell

function Set-ETradeShortcut {
    param(
        [string]$LinkPath,
        [string]$TargetPath,
        [string]$Arguments = "",
        [string]$Description,
        [int]$WindowStyle = 1
    )
    $parent = Split-Path -Parent $LinkPath
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if (Test-Path $LinkPath) {
        Remove-Item $LinkPath -Force
    }
    $shortcut = $shell.CreateShortcut($LinkPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $root
    if ($launchTarget -like "*.exe" -and (Test-Path $launchTarget)) {
        $shortcut.IconLocation = "$launchTarget,0"
    } else {
        $shortcut.IconLocation = "$iconStable,0"
    }
    $shortcut.Description = $Description
    $shortcut.WindowStyle = $WindowStyle
    $shortcut.Save()
    if (Test-Path $setAppIdScript) {
        try {
            & $setAppIdScript -ShortcutPath $LinkPath -AppId $appId
        } catch {
            Write-Host "AppUserModelID skipped for $LinkPath"
        }
    }
    Write-Host "Shortcut: $LinkPath"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$startup = [Environment]::GetFolderPath("Startup")

Set-ETradeShortcut `
    -LinkPath (Join-Path $desktop "ETrade Trader.lnk") `
    -TargetPath $launchTarget `
    -Arguments $launchArgs `
    -Description 'E*TRADE Trader - Home, Agents, Trades, Settings, Activity'

if (Test-Path $agentsLauncher) {
    Set-ETradeShortcut `
        -LinkPath (Join-Path $desktop "Finance Agents.lnk") `
        -TargetPath $agentsLauncher `
        -Description 'E*TRADE Trader - Agents tab (review intelligence agent reports)'
}

Set-ETradeShortcut `
    -LinkPath (Join-Path $programs "ETrade Trader.lnk") `
    -TargetPath $launchTarget `
    -Arguments $launchArgs `
    -Description 'Finance agent strategies applied to E*TRADE account'

Set-ETradeShortcut `
    -LinkPath (Join-Path $startup "ETrade Trader.lnk") `
    -TargetPath $launchTarget `
    -Arguments $launchArgs `
    -Description 'Finance E*TRADE Trader desktop app'

if (Test-Path $serviceLauncher) {
    Set-ETradeShortcut `
        -LinkPath (Join-Path $startup "ETrade Background Service.lnk") `
        -TargetPath $serviceLauncher `
        -Description 'Finance E*TRADE background trading worker'
}

$phoneMonitorBat = Join-Path $root "Install Phone Monitor.bat"
if (Test-Path $phoneMonitorBat) {
    Set-ETradeShortcut `
        -LinkPath (Join-Path $desktop "Install Phone Monitor.lnk") `
        -TargetPath $phoneMonitorBat `
        -Description 'Install E*TRADE Trader monitor app on your phone'
}

$mobileRemoteBat = Join-Path $root "Start Mobile Remote Access.bat"
if (Test-Path $mobileRemoteBat) {
    Set-ETradeShortcut `
        -LinkPath (Join-Path $desktop "Mobile Remote Access.lnk") `
        -TargetPath $mobileRemoteBat `
        -Description 'Phone monitor tunnel - runs hidden in background'
}

$fixHomeBat = Join-Path $root "Fix Phone Home Screen.bat"
if (Test-Path $fixHomeBat) {
    Set-ETradeShortcut `
        -LinkPath (Join-Path $desktop "Fix Phone Home Screen.lnk") `
        -TargetPath $fixHomeBat `
        -Description 'Fix phone error 1033 - stable Wi-Fi home screen icon'
}

Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force -ErrorAction SilentlyContinue
$explorerCache = "$env:LOCALAPPDATA\Microsoft\Windows\Explorer"
if (Test-Path $explorerCache) {
    Get-ChildItem $explorerCache -Filter "iconcache*" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Shortcuts refreshed - desktop, Start Menu, and taskbar."
Write-Host "  Icon: $iconStable"
Write-Host "  Launch: $launchTarget"
Write-Host ""
Write-Host "Taskbar tip: unpin any old Python icon, then pin ETrade Trader from Start or the desktop."