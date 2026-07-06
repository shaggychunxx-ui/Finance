@echo off
setlocal EnableExtensions
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator access for firewall rules...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0allow_mobile_monitor_firewall.ps1"
echo.
pause
exit /b 0