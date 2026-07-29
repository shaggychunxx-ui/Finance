@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo The standalone E*TRADE Short Trader app has been removed.
echo Use ETrade Unified Trader for long + short sleeves in one window.
echo.
echo Installing / refreshing Unified Trader shortcut...
call "%~dp0Install ETrade Trader.bat"
exit /b %ERRORLEVEL%
