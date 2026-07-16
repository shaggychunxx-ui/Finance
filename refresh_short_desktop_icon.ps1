# Build midnight-palette Short Trader icon and refresh desktop / Start Menu shortcuts.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$TargetBat = Join-Path $Root "ETrade Short Trader.bat"
$ServiceVbs = Join-Path $Root "Start ETrade Short Background Service.vbs"
$IconName = "etrade_short_trader.ico"
$IconSource = Join-Path $Root $IconName
$IconDir = Join-Path $env:ProgramData "FinanceETrade"
$IconStable = Join-Path $IconDir $IconName
$AppId = "Finance.ETrade.ShortTrader.1"
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$SetAppId = Join-Path $Root "set_shortcut_appid.ps1"

if (-not (Test-Path $VenvPy)) {
    Write-Error "Run Install ETrade Short Trader.bat first — Python venv is missing."
}

Write-Host "Building midnight Short Trader icon..."
& $VenvPy (Join-Path $Root "create_short_app_icon.py") | Out-Host
if (-not (Test-Path $IconSource)) {
    Write-Error "Icon build failed — $IconName not found."
}

New-Item -ItemType Directory -Force -Path $IconDir | Out-Null
Copy-Item $IconSource $IconStable -Force

function New-ShortShortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$Arguments = "",
        [string]$Description,
        [int]$WindowStyle = 1
    )
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if (Test-Path $Path) { Remove-Item $Path -Force }
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $Target
    $lnk.Arguments = $Arguments
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$IconStable,0"
    $lnk.Description = $Description
    $lnk.WindowStyle = $WindowStyle
    $lnk.Save()
    if (Test-Path $SetAppId) {
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $SetAppId -ShortcutPath $Path -AppId $AppId
        } catch {
            Write-Host "AppUserModelID skipped for $Path"
        }
    }
    Write-Host "Shortcut: $Path"
}

if (-not (Test-Path $TargetBat)) { throw "Missing $TargetBat" }

New-ShortShortcut -Path (Join-Path $Desktop "ETrade Short Trader.lnk") -Target $TargetBat -Description "ETrade Short Trader - midnight palette - SELL_SHORT / BUY_TO_COVER"

New-ShortShortcut -Path (Join-Path $StartMenu "ETrade Short Trader.lnk") -Target $TargetBat -Description "ETrade Short Trader - midnight palette - SELL_SHORT / BUY_TO_COVER"

if (Test-Path $ServiceVbs) {
    New-ShortShortcut -Path (Join-Path $Startup "ETrade Short Background Service.lnk") -Target "wscript.exe" -Arguments "`"$ServiceVbs`"" -Description "ETrade Short Trader background worker" -WindowStyle 7
}

Write-Host ""
Write-Host "Midnight Short Trader icons ready:"
Write-Host "  $IconSource"
Write-Host "  $IconStable"
Write-Host "  Desktop + Start Menu (+ Startup service if present)"
