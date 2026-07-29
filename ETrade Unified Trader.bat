@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM PowerShell launcher: prefer base pythonw (no venv double-process flash) + single GUI.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_unified_trader.ps1"
if errorlevel 1 (
    echo Launch failed.
    pause
    exit /b 1
)
exit /b 0
