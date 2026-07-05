@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PYW=%ROOT%.venv\Scripts\pythonw.exe"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "GUI=%ROOT%launch_etrade_trader.py"

if not exist "%PY%" (
    echo Setting up E*TRADE Trader environment...
    python -m venv "%ROOT%.venv"
    if errorlevel 1 goto :fail
    "%PY%" -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 goto :fail
)

if not exist "%GUI%" (
    echo ERROR: GUI missing at %GUI%
    pause
    exit /b 1
)

if not exist "%ROOT%etrade_config.json" (
    if exist "%ROOT%etrade_config.example.json" (
        copy /Y "%ROOT%etrade_config.example.json" "%ROOT%etrade_config.json" >nul
        echo Created etrade_config.json — add your API keys before connecting.
    )
)

start "ETradeTrader" /D "%ROOT%" "%PYW%" "%GUI%"
exit /b 0

:fail
echo Setup failed. Ensure Python 3.10+ is installed.
pause
exit /b 1