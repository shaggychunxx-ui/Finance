Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
Dim root, py
root = sh.CurrentDirectory
py = root & "\.venv\Scripts\python.exe"
If CreateObject("Scripting.FileSystemObject").FileExists(py) = False Then
  py = "python"
End If
sh.Run """" & py & """ """ & root & "\short_worker.py"" --service", 0, False
