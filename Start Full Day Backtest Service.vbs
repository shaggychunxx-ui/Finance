' Silent resume of the 2000-01-01 day-by-day walk-forward (no GUI).
Option Explicit
Dim sh, fs, root, pyw, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
pyw = root & ".venv\Scripts\pythonw.exe"
If Not fs.FileExists(pyw) Then pyw = "pythonw"
script = root & "run_full_day_backtest.py"
sh.CurrentDirectory = root
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Environment("Process")("PATH") = root & ".venv\Scripts;" & sh.Environment("Process")("PATH")
If fs.FileExists(script) Then
  sh.Run """" & pyw & """ """ & script & """ --no-gui --review-seconds 0 --seconds-per-day 1.25 --max-symbols 16 --max-agents 20", 0, False
End If
