@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo E*TRADE Trader - Install Phone Monitor
echo.
echo This will:
echo   1. Start the mobile monitor on your PC
echo   2. Create a remote link for your phone
echo   3. Open it on your USB-connected phone
echo   4. Let you add it to your home screen as an app
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Run Install ETrade Trader.bat first.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_phone_monitor.ps1"
set "INSTALL_EXIT=%ERRORLEVEL%"
if "%INSTALL_EXIT%"=="1" (
    echo.
    echo Phone monitor install failed. See messages above.
    pause
    exit /b 1
)

echo.
pause
exit /b 0