' Silent short worker — pythonw only (never python.exe).
Option Explicit
Dim sh, fs, root, pyw, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
pyw = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe"
If Not fs.FileExists(pyw) Then pyw = root & ".venv\Scripts\pythonw.exe"
If Not fs.FileExists(pyw) Then pyw = "pythonw"
script = root & "short_worker.py"
sh.CurrentDirectory = root
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Environment("Process")("PATH") = root & ".venv\Scripts;" & sh.Environment("Process")("PATH")
If fs.FileExists(script) Then
  sh.Run """" & pyw & """ """ & script & """ --service", 0, False
End If
