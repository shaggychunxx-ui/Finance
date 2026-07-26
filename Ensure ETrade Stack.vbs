' Silent ensure — NO console. Only starts stack if heartbeats are clearly dead.
' Never restarts a healthy stack (prevents restart thrash + window spam).
Option Explicit
Dim sh, fs, root, launcher
Dim ageSup, ageWd, ageWk
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
launcher = root & "Start ETrade Background Service.vbs"

' Require ALL three heartbeats stale > 3 minutes before doing anything.
ageSup = HeartbeatAgeSec(root & "output\finance_supervisor_heartbeat.txt")
ageWd = HeartbeatAgeSec(root & "output\pipeline_watchdog_heartbeat.txt")
ageWk = HeartbeatAgeSec(root & "output\etrade_worker_heartbeat.txt")

' If any layer is fresh, exit silently — stack is fine.
If ageSup < 180 Then WScript.Quit 0
If ageWd < 180 Then WScript.Quit 0
If ageWk < 180 Then WScript.Quit 0

' All stale/missing — start once (hidden).
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
