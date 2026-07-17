$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$TargetBat = Join-Path $Root "ETrade Unified Trader.bat"
$Icon = Join-Path $Root "etrade_short_trader.ico"
if (-not (Test-Path $Icon)) { $Icon = Join-Path $Root "etrade_trader.ico" }
$AppId = "Finance.ETrade.UnifiedTrader.1"
$SetAppId = Join-Path $Root "set_shortcut_appid.ps1"

function New-UShortcut($Path, $Target, $WorkDir, $IconPath) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $Target
    $lnk.WorkingDirectory = $WorkDir
    if (Test-Path $IconPath) { $lnk.IconLocation = "$IconPath,0" }
    $lnk.Description = "ETrade Unified Trader - Long and Short sleeves"
    $lnk.Save()
    if (Test-Path $SetAppId) {
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $SetAppId -ShortcutPath $Path -AppId $AppId
        } catch {}
    }
}

if (-not (Test-Path $TargetBat)) { throw "Missing $TargetBat" }
New-UShortcut (Join-Path $Desktop "ETrade Unified Trader.lnk") $TargetBat $Root $Icon
New-UShortcut (Join-Path $StartMenu "ETrade Unified Trader.lnk") $TargetBat $Root $Icon
Write-Host "Unified shortcuts ready."
