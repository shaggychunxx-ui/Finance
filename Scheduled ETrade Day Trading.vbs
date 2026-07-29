Option Explicit
Dim sh, fs, root, pyw, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
pyw = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe"
If Not fs.FileExists(pyw) Then pyw = root & ".venv\Scripts\pythonw.exe"
script = root & "run_etrade_day_trading.py"
If Not fs.FileExists(pyw) Or Not fs.FileExists(script) Then WScript.Quit 1
sh.CurrentDirectory = root
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Run """" & pyw & """ """ & script & """", 0, False
