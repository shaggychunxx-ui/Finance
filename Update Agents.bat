@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Updating agents from GitHub (shaggychunxx-ui/Finance)...
echo Includes main branch + open agent feature branches with new packages.

git --version >nul 2>&1
if errorlevel 1 (
    echo Git is not installed. Install Git for Windows, then run this again.
    pause
    exit /b 1
)

git fetch origin --prune
if errorlevel 1 goto :fail

echo.
echo [1/3] Refreshing agents from origin/main...
git checkout origin/main -- agents/
if errorlevel 1 goto :fail

echo [2/3] Installing new agent packages from feature branches...
REM Short-selling mechanics
git checkout origin/copilot/microstructure-hard-to-borrow-dynamics -- agents/bear_thesis agents/ftd_regsho agents/htb_dynamics agents/risk_mitigation agents/squeeze_mechanics 2>nul
REM Day-trading / portfolio / risk
git checkout origin/copilot/create-agent-for-day-trading-topics -- agents/day_trading_microstructure agents/long_squeeze_synergy agents/portfolio_frameworks agents/risk_protection 2>nul
REM Fundamental / technical / regime suite
git checkout origin/copilot/create-fundamental-analyst-agent -- agents/adversarial_debate agents/fundamental_analyst agents/market_regime agents/risk_guardrail agents/sentiment_alt_data agents/technical_pattern 2>nul
REM Macro / index / alt-data agents
git checkout origin/copilot/new-agent-yet-again -- agents/ftse100 2>nul
git checkout origin/copilot/new-agent-please-work -- agents/economy 2>nul
git checkout origin/copilot/new-agent-one-more-time -- agents/nikkei 2>nul
git checkout origin/copilot/new-agent-another-one -- agents/fred 2>nul
git checkout origin/copilot/new-agent-again -- agents/cpi 2>nul
git checkout origin/copilot/new-agent -- agents/earthdata 2>nul
git checkout origin/copilot/new-agent-f468a71e-e2fb-4c7e-9296-93a9cc734125 -- agents/consumer_sentiment 2>nul
REM Factor / microstructure extensions
git checkout origin/copilot/new-agent-c347f729-af5c-461f-9b4b-8995ec5464cd -- agents/borrow_fees 2>nul
git checkout origin/copilot/new-agent-06b0d22d-908e-472d-be84-f75a56793bf7 -- agents/capital_return 2>nul
git checkout origin/copilot/new-agent-3738c693-e7ea-4cef-bac3-96605fd64bdb -- agents/china_em_divergence 2>nul
git checkout origin/copilot/new-agent-84427e6b-03bd-4dc4-9742-a652215aa6c4 -- agents/content_integrity 2>nul
git checkout origin/copilot/new-agent-1111334e-cc8d-45d0-bb38-d5f585f63eb5 -- agents/corporate_credit 2>nul
git checkout origin/copilot/new-agent-e62a890e-f0cd-4e7c-9add-b75596a8d725 -- agents/correlation_breakdown 2>nul
git checkout origin/copilot/new-agent-1376bb68-0992-4e52-b88d-4da60cdca03e -- agents/crowding_quality 2>nul
git checkout origin/copilot/new-agent-4f4c1b32-95e9-4a6a-8d0e-7e8eff015d0b -- agents/dark_pool_volume_profile 2>nul
git checkout origin/copilot/new-agent-f7ea2821-9281-4319-9415-a2a2c8f9366f -- agents/earnings_calendar 2>nul
git checkout origin/copilot/new-agent-683ce957-0b36-4261-a4ce-78a1465cfe8a -- agents/equity_structuring 2>nul
git checkout origin/copilot/new-agent-b306503d-a618-4d50-9a73-562104d5ffd3 -- agents/estimate_revisions 2>nul
git checkout origin/copilot/new-agent-724c7830-8e71-47b7-b873-c1d04d6eb069 -- agents/etf_mechanics 2>nul
git checkout origin/copilot/new-agent-8408729d-63f5-4e06-b28f-2f26ac8a0d34 -- agents/fed_policy 2>nul
git checkout origin/copilot/new-agent-2d860908-114e-442f-87b6-dbc9c0c30ea9 -- agents/insider_clusters 2>nul
git checkout origin/copilot/new-agent-00e0ec16-42da-425c-99f2-603aef1f426e -- agents/margin_stress 2>nul
git checkout origin/copilot/structural-mechanics-information-microstructure -- agents/market_makers 2>nul
git checkout origin/copilot/new-agent-d8f5f3ff-acc6-4817-a2ff-fc5dbbcde892 -- agents/momentum_reversion 2>nul
git checkout origin/copilot/new-agent-core-mechanics -- agents/options_flow 2>nul
git checkout origin/copilot/new-agent-137d0a94-b7b2-4668-8a62-33cac0587099 -- agents/quality_factor 2>nul
git checkout origin/copilot/new-agent-e2db601e-c3e9-4ac7-9e90-4bb0513620ee -- agents/sector_rotation 2>nul

REM Keep shared market_data helpers from main (feature branches only have stubs)
git checkout origin/main -- agents/market_data 2>nul

if exist "output\agent_catalog_cache.json" del /f /q "output\agent_catalog_cache.json"

echo [3/3] Reconciling main.py RUNNERS with discovered packages...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "tools\sync_agent_runners.py"
) else (
    python "tools\sync_agent_runners.py"
)
if errorlevel 1 (
    echo Warning: runner sync script failed — agents may still run via package discovery.
)

echo.
echo Done. Agents installed from:
echo   https://github.com/shaggychunxx-ui/Finance
echo   (main + copilot agent branches)
echo.
echo Restart E*TRADE Trader / Short Trader / background worker to load new agents.
pause
exit /b 0

:fail
echo Update failed.
pause
exit /b 1
