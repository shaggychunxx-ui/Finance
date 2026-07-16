@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PYW=%ROOT%.venv\Scripts\pythonw.exe"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "GUI=%ROOT%launch_short_trader.py"

if not exist "%PY%" (
    echo Setting up environment...
    python -m venv "%ROOT%.venv"
    if errorlevel 1 goto :fail
    "%PY%" -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 goto :fail
)

if not exist "%ROOT%short_etrade_config.json" (
    if exist "%ROOT%short_etrade_config.example.json" (
        copy /Y "%ROOT%short_etrade_config.example.json" "%ROOT%short_etrade_config.json" >nul
        echo Created short_etrade_config.json — inherits keys from etrade_config.json when possible.
    )
)

if exist "%PYW%" (
    start "ETradeShortTrader" /D "%ROOT%" "%PYW%" "%GUI%"
) else (
    start "ETradeShortTrader" /D "%ROOT%" "%PY%" "%GUI%"
)
exit /b 0

:fail
echo Setup failed. Ensure Python 3.10+ is installed.
pause
exit /b 1
