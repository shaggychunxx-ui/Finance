' Start mobile remote access (monitor + Cloudflare tunnel) hidden in background.
Option Explicit
Dim sh, fs, root, ps1
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 1) <> "\" Then root = root & "\"
ps1 = root & "start_mobile_remote_background.ps1"
If Not fs.FileExists(ps1) Then WScript.Quit 1
sh.CurrentDirectory = root
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """", 0, False