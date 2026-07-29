# Install process continuum watchdog (1-minute tick + immediate start).
# Keeps finance_supervisor â†’ pipeline_watchdog â†’ etrade_worker alive.
# Run: powershell -ExecutionPolicy Bypass -File "Install Continuum Watchdog.ps1"
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Vbs = Join-Path $Root "Ensure Continuum Tick.vbs"
$TaskName = "FinanceProcessContinuumWatchdog"
$PywPreferred = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe"
$WatchdogPy = Join-Path $Root "process_continuum_watchdog.py"

if (-not (Test-Path $WatchdogPy)) {
    Write-Error "Missing $WatchdogPy"
    exit 1
}

$VbsContent = @"
' Silent tick: start process_continuum_watchdog.py if not already running.
Option Explicit
Dim sh, fso, root, pyw, script, wmi, procs, p, found
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
script = root & "process_continuum_watchdog.py"
If Not fso.FileExists(script) Then WScript.Quit 0

pyw = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = root & ".venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw"

found = False
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='pythonw.exe' OR Name='python.exe'")
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(1, p.CommandLine, "process_continuum_watchdog.py", 1) > 0 Then found = True
  End If
Next
On Error GoTo 0
If found Then WScript.Quit 0

sh.CurrentDirectory = root
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Environment("Process")("PYTHONUNBUFFERED") = "1"
sh.Environment("Process")("PATH") = root & ".venv\Scripts;" & sh.Environment("Process")("PATH")
sh.Run """" & pyw & """ """ & script & """", 0, False
WScript.Quit 0
"@
Set-Content -Path $Vbs -Value $VbsContent -Encoding ASCII

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
} catch {}

$action = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument "//B //Nologo `"$Vbs`"" `
    -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

# Also keep the 5-min stack ensure (space-safe) if missing
$ensureVbs = Join-Path $Root "Ensure ETrade Stack.vbs"
if (Test-Path $ensureVbs) {
    $wdTask = "Finance ETrade Worker Watchdog"
    try {
        Unregister-ScheduledTask -TaskName $wdTask -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        $wdAction = New-ScheduledTaskAction -Execute "wscript.exe" `
            -Argument "//B //Nologo `"$ensureVbs`"" -WorkingDirectory $Root
        $wdTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) `
            -RepetitionDuration (New-TimeSpan -Days 3650)
        $wdSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $wdTask -Action $wdAction -Trigger $wdTrigger `
            -Settings $wdSettings -Principal $principal -Force | Out-Null
        Write-Host "Refreshed 5-min ensure: $wdTask"
    } catch {
        Write-Host "5-min ensure refresh note: $($_.Exception.Message)"
    }
}

Write-Host "Installed scheduled task: $TaskName (every 1 minute)"
Write-Host "VBS: $Vbs"
Write-Host "Watchdog: $WatchdogPy"

# Start immediately
Start-Process -FilePath "wscript.exe" -ArgumentList @("//B", "//Nologo", "`"$Vbs`"") -WindowStyle Hidden -WorkingDirectory $Root
Start-Sleep -Seconds 3

Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State
Get-ScheduledTaskInfo -TaskName $TaskName | Format-List NextRunTime, LastTaskResult

$alive = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'process_continuum_watchdog' }
if ($alive) {
    Write-Host "Continuum watchdog running: PID=$(($alive | Select-Object -First 1).ProcessId)"
} else {
    Write-Host "WARNING: continuum process not detected yet - task will retry in 1 min"
}

