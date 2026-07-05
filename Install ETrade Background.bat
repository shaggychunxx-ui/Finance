@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Installing E*TRADE background worker...

if not exist ".venv\Scripts\python.exe" (
    python -m venv ".venv"
    if errorlevel 1 goto :fail
    ".venv\Scripts\pip.exe" install -r "requirements.txt"
    if errorlevel 1 goto :fail
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_etrade_background.ps1"
if errorlevel 1 goto :fail

echo.
echo Background worker installed.
echo   - Starts automatically when you log in to Windows
echo   - GUI and background worker start at Windows login
echo   - One background service handles agents, swing, and day trading (no duplicate tasks)
echo   - Log: output\etrade_worker.log
echo.
echo Connect E*TRADE once in the GUI app so the worker can trade your account.
pause
exit /b 0

:fail
echo Install failed.
pause
exit /b 1