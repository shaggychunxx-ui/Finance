' Quiet worker + external ensure (recovers when worker dies mid-pipeline).
Option Explicit
Dim sh, fs, root, py, worker, ensure, venv
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
venv = root & ".venv"

' Base python.exe — not .venv\Scripts\python.exe (avoids fake dual-PID tree).
py = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\python.exe"
If Not fs.FileExists(py) Then py = venv & "\Scripts\python.exe"
If Not fs.FileExists(py) Then WScript.Quit 1

worker = root & "etrade_worker.py"
ensure = root & "ensure_silent_worker.py"
sh.CurrentDirectory = root
sh.Environment("Process")("VIRTUAL_ENV") = venv
sh.Environment("Process")("PYTHONPATH") = root & ";" & venv & "\Lib\site-packages"
sh.Environment("Process")("PATH") = venv & "\Scripts;" & sh.Environment("Process")("PATH")
sh.Environment("Process")("FINANCE_PYTHON") = py
sh.Environment("Process")("FINANCE_AGENT_SUBPROCESS") = "1"
sh.Environment("Process")("FINANCE_SPLIT_PIPELINES") = "1"
' Research runs in isolated child; dedicated cycle when badly stale
sh.Environment("Process")("FINANCE_RUN_RESEARCH") = "1"
sh.Environment("Process")("FINANCE_RESEARCH_DEDICATED") = "1"
sh.Environment("Process")("FINANCE_PREDICTOR_FETCH_PRICES") = "0"
sh.Environment("Process")("FINANCE_PREDICTOR_TIMEOUT_SEC") = "90"
sh.Environment("Process")("PYTHONIOENCODING") = "utf-8"
sh.Environment("Process")("PYTHONUNBUFFERED") = "1"

' 0 = hidden, False = don't wait
sh.Run """" & py & """ -u """ & worker & """ --service", 0, False
sh.Run """" & py & """ -u """ & ensure & """", 0, False
