' Silent night-only continuous full-day walk-forward backtest
Option Explicit
Dim sh, fs, root, pyw, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
pyw = root & ".venv\Scripts\pythonw.exe"
If Not fs.FileExists(pyw) Then pyw = root & ".venv\Scripts\python.exe"
If Not fs.FileExists(pyw) Then
  ' Do not fall back to global pythonw — avoids duplicate services.
  WScript.Quit 1
End If
script = root & "run_backtest_loop.py"
sh.CurrentDirectory = root
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Environment("Process")("PATH") = root & ".venv\Scripts;" & sh.Environment("Process")("PATH")
If fs.FileExists(script) Then
  sh.Run """" & pyw & """ """ & script & """ --service", 0, False
End If
