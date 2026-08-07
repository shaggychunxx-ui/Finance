' run-hidden.vbs — launch a PowerShell script with NO console flash.
' Usage (Task Scheduler):
'   Program: wscript.exe
'   Arguments: //B //Nologo "C:\path\to\run-hidden.vbs" "C:\path\to\script.ps1" [extra args...]
'
' Prefers repo .local\run-silent.exe (CREATE_NO_WINDOW, Windows subsystem).
' Falls back to WScript.Shell.Run with window style 0.

Option Explicit
If WScript.Arguments.Count < 1 Then
  WScript.Quit 1
End If

Dim fso, sh, ps1, repo, silent, ps, cmd, rc, extra, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

ps1 = WScript.Arguments(0)
If Not fso.FileExists(ps1) Then WScript.Quit 1

' run-hidden.vbs lives in repo root next to .local\run-silent.exe
repo = fso.GetParentFolderName(WScript.ScriptFullName)
silent = repo & "\.local\run-silent.exe"
ps = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"

extra = ""
For i = 1 To WScript.Arguments.Count - 1
  extra = extra & " " & WScript.Arguments(i)
Next

If fso.FileExists(silent) Then
  cmd = """" & silent & """ """ & ps & """ -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & ps1 & """" & extra
  rc = sh.Run(cmd, 0, True)
  WScript.Quit rc
End If

cmd = """" & ps & """ -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """" & extra
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
