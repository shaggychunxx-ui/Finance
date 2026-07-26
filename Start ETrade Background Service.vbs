' Start immortal Finance stack with base pythonw (no venv re-exec flash).
Option Explicit
Dim sh, fs, root, pyw, supervisor, venv, site
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"

' Prefer real install pythonw (avoids venv stub launching a second process)
pyw = ""
If fs.FileExists("C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe") Then
  pyw = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe"
End If
If pyw = "" And fs.FileExists(root & ".venv\Scripts\pythonw.exe") Then
  pyw = root & ".venv\Scripts\pythonw.exe"
End If
If pyw = "" Then pyw = "pythonw"

supervisor = root & "finance_supervisor.py"
sh.CurrentDirectory = root

' Point base pythonw at venv packages
venv = root & ".venv"
site = venv & "\Lib\site-packages"
sh.Environment("Process")("VIRTUAL_ENV") = venv
sh.Environment("Process")("PYTHONPATH") = root & ";" & site
sh.Environment("Process")("PATH") = venv & "\Scripts;" & sh.Environment("Process")("PATH")

If fs.FileExists(supervisor) Then
  sh.Run """" & pyw & """ """ & supervisor & """", 0, False
End If
