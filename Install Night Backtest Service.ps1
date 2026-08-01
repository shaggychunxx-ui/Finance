# Install night-only continuous full-day walk-forward backtest service.
# Runs only when US RTH is closed; pauses during 09:30–16:00 ET.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pyw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pyw)) { $Pyw = Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $Pyw)) { $Pyw = "pythonw" }

$Vbs = Join-Path $Root "Start Night Backtest Service.vbs"
$VbsContent = @"
' Silent night-only continuous full-day walk-forward backtest
Option Explicit
Dim sh, fs, root, pyw, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
pyw = root & ".venv\Scripts\pythonw.exe"
If Not fs.FileExists(pyw) Then pyw = "pythonw"
script = root & "run_backtest_loop.py"
sh.CurrentDirectory = root
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Environment("Process")("PATH") = root & ".venv\Scripts;" & sh.Environment("Process")("PATH")
If fs.FileExists(script) Then
  sh.Run """" & pyw & """ """ & script & """ --service", 0, False
End If
"@
Set-Content -Path $Vbs -Value $VbsContent -Encoding ASCII

$Startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$Lnk = Join-Path $Startup "Finance Night Full-Day Backtest.lnk"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($Lnk)
$sc.TargetPath = "wscript.exe"
$sc.Arguments = "`"$Vbs`""
$sc.WorkingDirectory = $Root
$sc.WindowStyle = 7
$sc.Description = "Night-only continuous full-day walk-forward backtest"
$sc.Save()

# Task Scheduler: start at logon + keep a watchdog every 30 min
$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$Vbs`"" -WorkingDirectory $Root
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$TriggerWatch = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 0)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "Finance Night Full-Day Backtest" -Action $Action -Trigger @($TriggerLogon, $TriggerWatch) -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host "Night backtest service installed:"
Write-Host "  $Vbs"
Write-Host "  $Lnk"
Write-Host "  Task: Finance Night Full-Day Backtest"
Write-Host "Mode: night-only continuous full-day (10k/400 when RTH closed)"
