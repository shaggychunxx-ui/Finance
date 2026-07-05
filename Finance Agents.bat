@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "VBS=%ROOT%Launch Finance Agents.vbs"

if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo Setting up E*TRADE Trader environment...
    call "%ROOT%Install ETrade Trader.bat"
    if errorlevel 1 goto :fail
)

if not exist "%VBS%" (
    echo ERROR: Launcher missing at %VBS%
    pause
    exit /b 1
)

wscript.exe "%VBS%"
exit /b 0

:fail
echo.
echo Setup failed. Ensure Python 3.10+ is installed and on PATH.
pause
exit /b 1