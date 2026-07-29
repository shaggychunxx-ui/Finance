# Install a quiet once-per-minute ensure task (survives ensure process death).
# Run: powershell -ExecutionPolicy Bypass -File "Install Ensure Task.ps1"
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Vbs = Join-Path $Root "Ensure Worker Tick.vbs"
$TaskName = "FinanceEnsureSilentWorker"

$VbsContent = @'
Option Explicit
Dim sh, fs, root, py, ensure, fso, wmi, procs, p, found
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
py = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\python.exe"
If Not fso.FileExists(py) Then py = root & ".venv\Scripts\python.exe"
If Not fso.FileExists(py) Then WScript.Quit 0
ensure = root & "ensure_silent_worker.py"
found = False
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='python.exe' OR Name='pythonw.exe'")
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(1, p.CommandLine, "ensure_silent_worker.py", 1) > 0 Then found = True
  End If
Next
On Error GoTo 0
If found Then WScript.Quit 0
sh.CurrentDirectory = root
sh.Environment("Process")("FINANCE_PYTHON") = py
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Environment("Process")("FINANCE_AGENT_SUBPROCESS") = "1"
sh.Environment("Process")("FINANCE_SPLIT_PIPELINES") = "1"
sh.Environment("Process")("FINANCE_RUN_RESEARCH") = "1"
sh.Environment("Process")("FINANCE_RESEARCH_DEDICATED") = "1"
sh.Environment("Process")("FINANCE_PREDICTOR_FETCH_PRICES") = "0"
sh.Run """" & py & """ -u """ & ensure & """", 0, False
'@
Set-Content -Path $Vbs -Value $VbsContent -Encoding ASCII

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$Vbs`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 1) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName (every 1 minute)"
Write-Host "VBS: $Vbs"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State
Get-ScheduledTaskInfo -TaskName $TaskName | Format-List NextRunTime, LastTaskResult
