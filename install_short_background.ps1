$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Vbs = Join-Path $Root "Start ETrade Short Background Service.vbs"
$Startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$Lnk = Join-Path $Startup "ETrade Short Background Service.lnk"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

$VbsContent = @"
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "$Root"
sh.Run """$Py"" ""$Root\short_worker.py"" --service", 0, False
"@
Set-Content -Path $Vbs -Value $VbsContent -Encoding ASCII

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($Lnk)
$sc.TargetPath = "wscript.exe"
$sc.Arguments = """$Vbs"""
$sc.WorkingDirectory = $Root
$sc.WindowStyle = 7
$sc.Description = "E*TRADE Short Trader background worker"
$sc.Save()

# Also Run key (optional dual with long worker — different mutex)
$RunName = "FinanceETradeShortBackgroundService"
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v $RunName /t REG_SZ /d "wscript.exe `"$Vbs`"" /f | Out-Null

Write-Host "Short background service installed:"
Write-Host "  $Lnk"
Write-Host "  HKCU Run: $RunName"
Write-Host "Defaults remain dry_run=true until you change short_etrade_config.json"
