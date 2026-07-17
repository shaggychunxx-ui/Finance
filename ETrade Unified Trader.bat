@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PYW=%ROOT%.venv\Scripts\pythonw.exe"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "GUI=%ROOT%unified_trader_gui.py"

if not exist "%PY%" (
    echo Setting up environment...
    python -m venv "%ROOT%.venv"
    if errorlevel 1 goto :fail
    "%PY%" -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 goto :fail
)

if exist "%PYW%" (
    start "ETradeUnified" /D "%ROOT%" "%PYW%" "%GUI%"
) else (
    start "ETradeUnified" /D "%ROOT%" "%PY%" "%GUI%"
)
exit /b 0

:fail
echo Setup failed. Ensure Python 3.10+ is installed.
pause
exit /b 1
