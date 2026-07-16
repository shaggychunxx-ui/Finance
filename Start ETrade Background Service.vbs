' Start hidden E*TRADE background service (continuous loop)
Option Explicit
Dim sh, fs, root, py, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
py = root & ".venv\Scripts\python.exe"
script = root & "etrade_worker.py"
If Not fs.FileExists(py) Then WScript.Quit 1
sh.CurrentDirectory = root
sh.Run """" & py & """ """ & script & """ --service", 0, False