# Rebuild icons and refresh Finance Agents desktop shortcut.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$icon = Join-Path $root "app_icon.ico"
$target = Join-Path $root "Launch Finance Agents.vbs"
$launcherExe = Join-Path $root "ETrade Trader.exe"
$iconFile = if (Test-Path $launcherExe) { $launcherExe } else { $icon }
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$shortcut = Join-Path $desktop "Finance Agents.lnk"
$startMenu = Join-Path $programs "Finance Agents.lnk"

if (-not (Test-Path $venvPy)) {
    Write-Error "Run Install Finance Agents.bat first."
}

& $venvPy (Join-Path $root "create_app_icon.py") | Out-Host
if (-not (Test-Path $icon)) {
    Write-Error "Icon build failed."
}

function Set-AgentsShortcut {
    param([string]$LinkPath)
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path $LinkPath) { Remove-Item $LinkPath -Force }
    $s = $shell.CreateShortcut($LinkPath)
    $s.TargetPath = $target
    $s.WorkingDirectory = $root
    $s.IconLocation = "$iconFile,0"
    $s.Description = "E*TRADE Trader - Agents tab (review intelligence agent reports)"
    $s.WindowStyle = 1
    $s.Save()
    Write-Host "Shortcut: $LinkPath"
}

Set-AgentsShortcut $shortcut
Set-AgentsShortcut $startMenu

Write-Host ""
Write-Host "Finance Agents icons and shortcuts refreshed."