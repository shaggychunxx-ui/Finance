@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up Finance agents...
    python -m venv .venv
    ".venv\Scripts\pip.exe" install -r requirements.txt
)

".venv\Scripts\python.exe" main.py %*