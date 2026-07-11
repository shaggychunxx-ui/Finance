@echo off
cd /d "%~dp0"
python run_backtest_loop.py --interval-minutes 60
pause
