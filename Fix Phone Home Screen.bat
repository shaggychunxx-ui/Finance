@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo E*TRADE Trader - Fix Phone Home Screen (error 1033)
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Run Install ETrade Trader.bat first.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_phone_homescreen.ps1"
if errorlevel 1 (
    echo.
    echo Fix failed. See messages above.
    pause
    exit /b 1
)

echo.
pause
exit /b 0