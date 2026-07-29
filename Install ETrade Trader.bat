@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Installing E*TRADE Unified Trader (only desktop app)...
echo Standalone Long Trader and Short Trader apps are no longer installed.
echo.

REM Prefer the robust PowerShell installer (Python discovery, tkinter check, venv, shortcuts)
if exist "%~dp0Install-ETrade-Unified-Trader.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-ETrade-Unified-Trader.ps1" -InPlace -InstallDir "%~dp0"
    if errorlevel 1 goto :fail
    goto :cleanup
)

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

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0refresh_unified_desktop_icon.ps1"
if errorlevel 1 goto :fail

:cleanup
REM Remove obsolete standalone shortcuts if present
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$paths = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'));" ^
  "foreach ($d in $paths) { foreach ($n in @('ETrade Trader.lnk','ETrade Short Trader.lnk')) { $p = Join-Path $d $n; if (Test-Path $p) { Remove-Item $p -Force; Write-Host \"Removed $p\" } } }"

echo.
echo Desktop shortcut: %USERPROFILE%\Desktop\ETrade Unified Trader.lnk
echo Start Menu: ETrade Unified Trader
echo.
echo Long + Short sleeves run inside the Unified window only.
echo Optional: Install ETrade Background.bat for headless worker when GUI is closed.
echo Optional: Start Silent Worker Only.vbs for quiet automation.
echo.
if /I not "%ETRADE_INSTALL_SILENT%"=="1" pause
exit /b 0

:fail
echo Install failed. Need Python 3.10+ on PATH with tcl/tk.
echo Download: https://www.python.org/downloads/
if /I not "%ETRADE_INSTALL_SILENT%"=="1" pause
exit /b 1
