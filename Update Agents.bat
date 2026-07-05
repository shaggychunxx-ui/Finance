@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Updating agents from GitHub (shaggychunxx-ui/Finance)...

git --version >nul 2>&1
if errorlevel 1 (
    echo Git is not installed. Install Git for Windows, then run this again.
    pause
    exit /b 1
)

git fetch origin main
if errorlevel 1 goto :fail

git checkout origin/main -- agents/
if errorlevel 1 goto :fail

if exist "output\agent_catalog_cache.json" del /f /q "output\agent_catalog_cache.json"

echo.
echo Agents updated from https://github.com/shaggychunxx-ui/Finance/tree/main/agents
echo Local trader helpers kept: platform_catalog.py, market_predictor.py, base.py
echo.
echo Restart the E*TRADE Trader app or background worker to use the new agents.
pause
exit /b 0

:fail
echo Update failed.
pause
exit /b 1