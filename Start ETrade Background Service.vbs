' Start hidden E*TRADE background service (continuous loop)
Option Explicit
Dim sh, fs, root, pyw, script, lock
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
pyw = root & ".venv\Scripts\pythonw.exe"
script = root & "etrade_worker.py"
If Not fs.FileExists(pyw) Then WScript.Quit 1
sh.CurrentDirectory = root
sh.Run """" & pyw & """ """ & script & """ --service", 0, False