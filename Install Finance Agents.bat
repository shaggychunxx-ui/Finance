@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Finance Agents is now a tab inside E*TRADE Trader.
echo Refreshing shortcuts to open the Agents tab...

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
echo Desktop shortcut created: %SHORTCUT%
echo Launcher: %TARGET%
echo.
echo Double-click "Finance Agents" on your desktop to open E*TRADE Trader on the Agents tab.
pause
exit /b 0

:fail
echo.
echo Install failed.
pause
exit /b 1