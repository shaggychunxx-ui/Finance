@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Installing Finance Agents (standalone agents UI)...
echo E*TRADE desktop trader UIs have been removed; pipeline/API/workers remain.
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python environment...
    python -m venv ".venv"
    if errorlevel 1 goto :fail
    ".venv\Scripts\pip.exe" install -r "requirements.txt"
    if errorlevel 1 goto :fail
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0refresh_finance_agents_icon.ps1"
if errorlevel 1 goto :fail

set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\Finance Agents.lnk"
set "TARGET=%~dp0Launch Finance Agents.vbs"

echo.
echo Desktop shortcut: %SHORTCUT%
echo Launcher: %TARGET%
echo.
echo Double-click "Finance Agents" to open the agents report UI.
echo Headless trading: Install ETrade Background.bat / Start Silent Worker Only.vbs
pause
exit /b 0

:fail
echo.
echo Install failed. Need Python 3.10+ on PATH with tcl/tk.
echo Download: https://www.python.org/downloads/
pause
exit /b 1
