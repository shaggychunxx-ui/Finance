@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Installing E*TRADE Short Trader (sister app)...

if not exist ".venv\Scripts\python.exe" (
    python -m venv ".venv"
    if errorlevel 1 goto :fail
    ".venv\Scripts\pip.exe" install -r "requirements.txt"
    if errorlevel 1 goto :fail
)

if not exist "short_etrade_config.json" (
    if exist "short_etrade_config.example.json" (
        copy /Y "short_etrade_config.example.json" "short_etrade_config.json" >nul
        echo Created short_etrade_config.json
    )
)

echo Building midnight palette icons...
".venv\Scripts\python.exe" "create_short_app_icon.py"
if errorlevel 1 goto :fail

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0refresh_short_desktop_icon.ps1"
if errorlevel 1 goto :fail

echo.
echo Desktop shortcut: %%USERPROFILE%%\Desktop\ETrade Short Trader.lnk
echo Icon: etrade_short_trader.ico (Midnight palette)
echo Config: short_etrade_config.json  (inherits long-app API keys/tokens by default)
echo Output: output\short\
echo.
echo Defaults are SAFE:
echo   dry_run=true  live_trading=false  auto_execute=false
echo.
echo Next steps:
echo   1. Keep sandbox true until short/borrow previews succeed
echo   2. Launch ETrade Short Trader
echo   3. Build short plan / Preview orders
echo   4. Optional: Install ETrade Short Background.bat
echo.
pause
exit /b 0

:fail
echo Install failed.
pause
exit /b 1
