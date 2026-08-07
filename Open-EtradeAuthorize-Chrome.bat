@echo off
REM Open current E*TRADE authorize URL in Google Chrome (one window).
set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
set URL_FILE=%USERPROFILE%\Finance\output\last_authorize_url.txt
if not exist "%CHROME%" (
  echo Chrome not found: %CHROME%
  exit /b 1
)
if not exist "%URL_FILE%" (
  echo No URL file: %URL_FILE%
  echo Run: python begin_etrade_login.py --no-browser
  exit /b 1
)
set /p URL=<"%URL_FILE%"
start "" "%CHROME%" --new-window --start-maximized %URL%
echo Launched Chrome with authorize URL.
