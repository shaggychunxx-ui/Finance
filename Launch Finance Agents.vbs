' Launch standalone Finance Agents desktop UI (no E*TRADE trader GUI).
Option Explicit
Dim sh, fs, root, pyw, py, gui
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
gui = root & "finance_agents_gui.py"
If Not fs.FileExists(gui) Then
  MsgBox "finance_agents_gui.py not found.", vbCritical, "Finance Agents"
  WScript.Quit 1
End If
pyw = root & ".venv\Scripts\pythonw.exe"
py = root & ".venv\Scripts\python.exe"
sh.CurrentDirectory = root
If fs.FileExists(pyw) Then
  sh.Run """" & pyw & """ """ & gui & """", 1, False
ElseIf fs.FileExists(py) Then
  sh.Run """" & py & """ """ & gui & """", 1, False
Else
  MsgBox "Python venv missing." & vbCrLf & "Run Install Finance Agents.bat first.", vbCritical, "Finance Agents"
  WScript.Quit 1
End If
