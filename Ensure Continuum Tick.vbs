' Silent tick: start process_continuum_watchdog.py if not already running.
Option Explicit
Dim sh, fso, root, pyw, script, wmi, procs, p, found
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
script = root & "process_continuum_watchdog.py"
If Not fso.FileExists(script) Then WScript.Quit 0

pyw = "C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = root & ".venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw"

found = False
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='pythonw.exe' OR Name='python.exe'")
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(1, p.CommandLine, "process_continuum_watchdog.py", 1) > 0 Then found = True
  End If
Next
On Error GoTo 0
If found Then WScript.Quit 0

sh.CurrentDirectory = root
sh.Environment("Process")("VIRTUAL_ENV") = root & ".venv"
sh.Environment("Process")("PYTHONPATH") = root & ";" & root & ".venv\Lib\site-packages"
sh.Environment("Process")("PYTHONUNBUFFERED") = "1"
sh.Environment("Process")("PATH") = root & ".venv\Scripts;" & sh.Environment("Process")("PATH")
sh.Run """" & pyw & """ """ & script & """", 0, False
WScript.Quit 0
