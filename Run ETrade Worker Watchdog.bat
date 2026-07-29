@echo off
REM Fully silent ensure — wscript //B never shows a console.
cd /d "%~dp0"
wscript.exe //B //Nologo "%~dp0Ensure ETrade Stack.vbs"
exit /b 0
