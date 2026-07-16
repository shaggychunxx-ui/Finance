' Scheduled day trading — intraday entries and exits during market hours
Option Explicit
Dim sh, fs, root, pyw, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
py = root & ".venv\Scripts\python.exe"
script = root & "run_etrade_day_trading.py"
If Not fs.FileExists(py) Then WScript.Quit 1
sh.CurrentDirectory = root
sh.Run """" & py & """ """ & script & """", 0, False