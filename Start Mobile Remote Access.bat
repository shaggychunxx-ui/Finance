@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo E*TRADE Trader - Mobile Remote Access (background)
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Run Install ETrade Trader.bat first.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_mobile_remote_background.ps1"
if errorlevel 1 (
    echo.
    echo Could not start mobile remote access.
    pause
    exit /b 1
)

echo.
echo Running in the background. No window needs to stay open.
echo   Phone URL: output\mobile_phone_url.txt
echo   Log:       output\mobile_remote_access.log
echo   Stop:      Stop Mobile Remote Access.bat
echo.
pause
exit /b 0