@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Installing Short Trader background worker (optional)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_short_background.ps1"
if errorlevel 1 (
    echo Install failed.
    pause
    exit /b 1
)
echo Done.
pause
