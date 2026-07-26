@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PYW=C:\Users\Box One\AppData\Local\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=%ROOT%.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%ROOT%.venv\Scripts\python.exe"

set "VIRTUAL_ENV=%ROOT%.venv"
set "PYTHONPATH=%ROOT%;%ROOT%.venv\Lib\site-packages"
set "PATH=%ROOT%.venv\Scripts;%PATH%"

if not exist "%PYW%" (
  echo Python not found. Install Python 3.10+ or create .venv
  pause
  exit /b 1
)

start "ETradeUnified" /D "%ROOT%" "%PYW%" "%ROOT%unified_trader_gui.py"
exit /b 0