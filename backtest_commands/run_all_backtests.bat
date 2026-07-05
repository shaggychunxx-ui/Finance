@echo off
REM Runs every agent's backtest command file in sequence.
cd /d "%~dp0"

call combined-conditional.bat
call data-steward.bat
call datascience.bat
call electricity.bat
call empirical-probability.bat
call events.bat
call financial-data.bat
call finance.bat
call geopolitics.bat
call grid.bat
call logistics.bat
call markets.bat
call meteorology.bat
call patents.bat
call records-management.bat
call research-statistics.bat
call sales-analytics.bat
call theoretical-probability.bat
call transportation.bat
