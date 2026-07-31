' Launch watch-and-act.ps1 with ZERO console flash.
' Prefers .local\run-silent.exe (CREATE_NO_WINDOW). Falls back to wscript hidden Run.
Option Explicit
Dim sh, fso, repo, ps1, silent, ps, cmd, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
repo = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = repo & "\watch-and-act.ps1"
silent = repo & "\.local\run-silent.exe"
ps = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"

If Not fso.FileExists(ps1) Then WScript.Quit 1

If fso.FileExists(silent) Then
  cmd = """" & silent & """ """ & ps & """ -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & ps1 & """"
  rc = sh.Run(cmd, 0, True)
  WScript.Quit rc
End If

' Fallback: hidden window style (may still flash under Windows Terminal)
cmd = """" & ps & """ -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """"
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
