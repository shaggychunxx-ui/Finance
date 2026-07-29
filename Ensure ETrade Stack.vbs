' Silent ensure — NO console.
' Nudges the immortal stack when any layer's heartbeat is stale, and always
' starts process_continuum_watchdog.py if it is not already running.
Option Explicit
Dim sh, fs, root, launcher, continuum, pyw
Dim ageSup, ageWd, ageWk, ageCont
Dim foundCont
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
launcher = root & "Start ETrade Background Service.vbs"
continuum = root & "process_continuum_watchdog.py"

ageSup = HeartbeatAgeSec(root & "output\finance_supervisor_heartbeat.txt")
ageWd = HeartbeatAgeSec(root & "output\pipeline_watchdog_heartbeat.txt")
ageWk = HeartbeatAgeSec(root & "output\etrade_worker_heartbeat.txt")
ageCont = HeartbeatAgeSec(root & "output\process_continuum_watchdog_heartbeat.txt")

' Always keep continuum layer up (it heals the other three).
foundCont = ProcessRunning("process_continuum_watchdog.py")
If (Not foundCont) Or (ageCont >= 180) Then
  pyw = ResolvePyw()
  If fs.FileExists(continuum) And pyw <> "" Then
    sh.CurrentDirectory = root
    sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
    sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
    sh.Environment("Process")("PATH") = root & ".venv\Scripts;" & sh.Environment("Process")("PATH")
    sh.Run """" & pyw & """ """ & continuum & """", 0, False
  End If
End If

' Healthy stack: all three service layers heartbeating within 3 minutes.
If ageSup < 180 And ageWd < 180 And ageWk < 180 Then WScript.Quit 0

' Otherwise start full stack once (supervisor singleton + continuum).
If fs.FileExists(launcher) Then
  sh.Run "wscript.exe //B //Nologo """ & launcher & """", 0, False
End If
WScript.Quit 0

Function HeartbeatAgeSec(path)
  Dim f
  On Error Resume Next
  HeartbeatAgeSec = 99999
  If Not fs.FileExists(path) Then Exit Function
  Set f = fs.GetFile(path)
  HeartbeatAgeSec = DateDiff("s", f.DateLastModified, Now)
  If HeartbeatAgeSec < 0 Then HeartbeatAgeSec = 0
  If Err.Number <> 0 Then HeartbeatAgeSec = 99999
End Function

Function ResolvePyw()
  ResolvePyw = ""
  If fs.FileExists("C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe") Then
    ResolvePyw = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe"
    Exit Function
  End If
  If fs.FileExists(root & ".venv\Scripts\pythonw.exe") Then
    ResolvePyw = root & ".venv\Scripts\pythonw.exe"
  End If
End Function

Function ProcessRunning(needle)
  Dim wmi, procs, p
  ProcessRunning = False
  On Error Resume Next
  Set wmi = GetObject("winmgmts:\\.\root\cimv2")
  Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='pythonw.exe' OR Name='python.exe'")
  For Each p In procs
    If Not IsNull(p.CommandLine) Then
      If InStr(1, p.CommandLine, needle, 1) > 0 Then
        ProcessRunning = True
        Exit Function
      End If
    End If
  Next
  On Error GoTo 0
End Function
