Option Explicit

Dim sh, fs, root, pyw, gui

Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"

pyw = root & ".venv\Scripts\pythonw.exe"
gui = root & "launch_etrade_trader.py"

If Not fs.FileExists(pyw) Then
    sh.Run "cmd /c """ & Chr(34) & root & "ETrade Trader.bat" & Chr(34) & """", 1, True
End If

If Not fs.FileExists(pyw) Then
    MsgBox "E*TRADE Trader setup failed.", vbCritical, "E*TRADE Trader"
    WScript.Quit 1
End If

sh.CurrentDirectory = root
sh.Run """" & pyw & """ """ & gui & """", 0, False