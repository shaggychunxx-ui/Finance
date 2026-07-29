@echo off
REM Legacy name — launches Unified Trader only (standalone short app removed).
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0ETrade Unified Trader.bat"
exit /b %ERRORLEVEL%
