@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo E*TRADE Trader — Mobile Monitor
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Run Install ETrade Trader.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "mobile_monitor.py"
pause
exit /b %ERRORLEVEL%