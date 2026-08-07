@echo off
REM Start E*TRADE phone LAN bridge on live runtime (GROMIT).
set "LIVE=%USERPROFILE%\Finance"
if not "%FINANCE_RUNTIME%"=="" set "LIVE=%FINANCE_RUNTIME%"
if not exist "%LIVE%\phone_bridge.py" set "LIVE=%~dp0"

cd /d "%LIVE%"
if exist "%LIVE%\.venv\Scripts\pythonw.exe" (
  start "" "%LIVE%\.venv\Scripts\pythonw.exe" "%LIVE%\phone_bridge.py"
) else (
  start "" pythonw "%LIVE%\phone_bridge.py"
)
echo Started phone_bridge from %LIVE%
