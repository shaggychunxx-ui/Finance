@echo off
REM International Air Freight Tracker launcher.
REM Usage:
REM   run.bat                 - start the web dashboard
REM   run.bat cli <args...>   - run the CLI, e.g. run.bat cli list

setlocal
cd /d "%~dp0"

if "%1"=="cli" (
    shift
    python main.py %*
) else (
    python app.py
)

endlocal
