@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Installing E*TRADE Trader desktop app...

if not exist ".venv\Scripts\python.exe" (
    python -m venv ".venv"
    if errorlevel 1 goto :fail
    ".venv\Scripts\pip.exe" install -r "requirements.txt"
    if errorlevel 1 goto :fail
)

if not exist "etrade_config.json" (
    if exist "etrade_config.example.json" (
        copy /Y "etrade_config.example.json" "etrade_config.json" >nul
        echo Created etrade_config.json — edit with your E*TRADE API keys.
    )
)

".venv\Scripts\python.exe" "build_etrade_launcher.py"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0refresh_desktop_icon.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0refresh_finance_agents_icon.ps1"

echo.
echo Desktop shortcuts:
echo   %USERPROFILE%\Desktop\ETrade Trader.lnk
echo   %USERPROFILE%\Desktop\Finance Agents.lnk  (opens Agents tab)
echo Start Menu: %APPDATA%\Microsoft\Windows\Start Menu\Programs\ETrade Trader.lnk
echo.
echo One app — tabs: Home, Agents, Trades, Settings, Activity
echo Trades: Balance, History/P&L, Attribution, Portfolio, Swing, Day
echo.
echo Next steps:
echo   1. Edit etrade_config.json with your E*TRADE consumer key/secret
echo   2. Keep sandbox: true for testing
echo   3. Launch ETrade Trader and click Connect
echo   4. Confirm your brokerage account in Settings
echo   5. Optional: Install ETrade Background.bat for automation when GUI is closed
echo   6. Phone monitor: Start Mobile Remote Access.bat (runs hidden in background)
echo.
echo Installing Windows startup entries...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_etrade_background.ps1"
if errorlevel 1 goto :fail
pause
exit /b 0

:fail
echo Install failed.
pause
exit /b 1