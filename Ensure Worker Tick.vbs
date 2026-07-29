Option Explicit
Dim sh, fs, root, py, ensure, fso, wmi, procs, p, found
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
py = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\python.exe"
If Not fso.FileExists(py) Then py = root & ".venv\Scripts\python.exe"
If Not fso.FileExists(py) Then WScript.Quit 0
ensure = root & "ensure_silent_worker.py"
found = False
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='python.exe' OR Name='pythonw.exe'")
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(1, p.CommandLine, "ensure_silent_worker.py", 1) > 0 Then found = True
  End If
Next
On Error GoTo 0
If found Then WScript.Quit 0
sh.CurrentDirectory = root
sh.Environment("Process")("FINANCE_PYTHON") = py
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Environment("Process")("FINANCE_AGENT_SUBPROCESS") = "1"
sh.Environment("Process")("FINANCE_SPLIT_PIPELINES") = "1"
sh.Environment("Process")("FINANCE_RUN_RESEARCH") = "1"
sh.Environment("Process")("FINANCE_RESEARCH_DEDICATED") = "1"
sh.Environment("Process")("FINANCE_PREDICTOR_FETCH_PRICES") = "0"
sh.Run """" & py & """ -u """ & ensure & """", 0, False
