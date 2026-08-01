@echo off
cd /d "%~dp0"
title Finance Full Day Walk-Forward Backtest
echo Starting full day backtest (slow, from 2000-01-01)...
echo Review window will open first. Resumes prior state unless --fresh is passed.
python run_full_day_backtest.py --seconds-per-day 1.25 --max-symbols 16 --max-agents 20 --review-seconds 45 %*
echo.
echo Backtest process ended with code %ERRORLEVEL%.
pause
