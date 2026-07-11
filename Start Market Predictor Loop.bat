@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo E*TRADE Trader - Market Predictor Loop
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Run Install ETrade Trader.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "run_pipeline_loop.py" %*
pause
exit /b %ERRORLEVEL%
