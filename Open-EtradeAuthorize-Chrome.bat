@echo off
REM Open authorize URL in DEFAULT Chrome profile (taskbar session) — once.
REM No --user-data-dir. No --new-window.
set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
set URL_FILE=%USERPROFILE%\Finance\output\last_authorize_url.txt
if not exist "%CHROME%" (
  echo Chrome not found: %CHROME%
  exit /b 1
)
if not exist "%URL_FILE%" (
  echo No URL file: %URL_FILE%
  exit /b 1
)
set /p URL=<"%URL_FILE%"
start "" "%CHROME%" %URL%
echo Opened once in default Chrome profile.
