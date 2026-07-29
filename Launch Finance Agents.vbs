' Opens Unified Trader (standalone long trader app removed).
Option Explicit
Dim sh, fs, root, bat
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
bat = root & "ETrade Unified Trader.bat"
If Not fs.FileExists(bat) Then
  MsgBox "ETrade Unified Trader.bat not found." & vbCrLf & "Run Install ETrade Unified if needed.", vbCritical, "Finance Agents"
  WScript.Quit 1
End If
sh.CurrentDirectory = root
sh.Run """" & bat & """", 1, False
