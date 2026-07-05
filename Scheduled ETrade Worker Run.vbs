' Silent scheduled E*TRADE worker - no console window
Option Explicit
Dim sh, fs, root, pyw, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
pyw = root & ".venv\Scripts\pythonw.exe"
script = root & "run_etrade_worker_once.py"
If Not fs.FileExists(pyw) Then WScript.Quit 1
sh.CurrentDirectory = root
sh.Run """" & pyw & """ """ & script & """", 0, False