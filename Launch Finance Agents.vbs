' Launch E*TRADE Trader on the Agents tab (Finance Agents is integrated there).
Option Explicit

Dim sh, fs, root, pyw, launcher, exe

Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"

exe = root & "ETrade Trader.exe"
launcher = root & "launch_etrade_trader.py"
pyw = root & ".venv\Scripts\pythonw.exe"

If Not fs.FileExists(pyw) Then
    Dim setup
    setup = "cmd /c """ & Chr(34) & root & "Finance Agents.bat" & Chr(34) & """"
    sh.Run setup, 1, True
End If

If Not fs.FileExists(pyw) And Not fs.FileExists(exe) Then
    MsgBox "E*TRADE Trader setup failed." & vbCrLf & "Run Install ETrade Trader.bat first.", vbCritical, "Finance Agents"
    WScript.Quit 1
End If

sh.CurrentDirectory = root
sh.Environment("Process")("ETRADE_TAB") = "agents"

If fs.FileExists(exe) Then
    sh.Run """" & exe & """", 0, False
Else
    sh.Run """" & pyw & """ """ & launcher & """", 0, False
End If