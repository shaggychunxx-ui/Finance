@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM If this bat lives inside the transfer folder, use it as -DataDir
set "DATA=%~dp0"
set "INSTALL="

REM Optional: first arg = install dir
if not "%~1"=="" set "INSTALL=%~1"

if defined INSTALL (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Import-ETrade-UserData.ps1" -DataDir "%DATA%" -InstallDir "%INSTALL%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Import-ETrade-UserData.ps1" -DataDir "%DATA%"
)
set ERR=%ERRORLEVEL%
if not "%ETRADE_INSTALL_SILENT%"=="1" pause
exit /b %ERR%
