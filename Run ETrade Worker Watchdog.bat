@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0ensure_etrade_worker.ps1"