@echo off
cd /d "%~dp0"
python run_market_predictor_loop.py --interval-minutes 30
pause
