# Finance

Intelligence agents for financial market analysis and a client-side world events tracker. Each agent pulls live public data and produces expert summaries with sector signals.

## Agents

| Agent | Command | Data source |
|-------|---------|-------------|
| **EIA Grid Monitor Analyst** | `run.bat electricity` | [EIA Grid Monitor US48](https://www.eia.gov/electricity/gridmonitor/dashboard/electric_overview/US48/US48) |
| **Electrical Grid Analyst** | `run.bat grid` | [Grid Status Live](https://www.gridstatus.io/live), ERCOT, CAISO, EIA |
| **Civil Transportation Analyst** | `run.bat transportation` | [data.transportation.gov](https://data.transportation.gov/) |
| **Patent Landscape Analyst** | `run.bat patents` | OpenAlex, IPWatchdog RSS, USPTO feeds |
| **World Events Tracker** | `run.bat events` | BBC World / NPR RSS |
| **Data Science Expert** | `run.bat datascience` | Yahoo Finance (6mo daily history) |
| **Google Finance Beta Analyst** | `run.bat finance` | [Google Finance Beta](https://www.google.com/finance/beta) |
| **Yahoo Finance Statistical Analyst** | `run.bat financial-data` | [Yahoo Finance](https://finance.yahoo.com/) |
| **Market Analyst Expert** | `run.bat markets` | [Yahoo Finance](https://finance.yahoo.com/) API |
| **Geopolitics Expert** | `run.bat geopolitics` | BBC World / NPR RSS (+ optional GDELT) |
| **Logistics Expert** | `run.bat logistics` | [MarineTraffic](https://www.marinetraffic.com/) AIS (optional key) |
| **Theoretical Probability Expert** | `run.bat theoretical-probability` | Yahoo Finance (6mo daily history) |
| **Empirical Probability Expert** | `run.bat empirical-probability` | Yahoo Finance (1yr daily history) |
| **Combined & Conditional Probability Expert** | `run.bat combined-conditional` | Yahoo Finance (1yr daily history) |
| **Research Statistics Expert** | `run.bat research-statistics` | Yahoo Finance (1yr daily history) |
| **Correlation Breakdown / Tail-Risk Expert** | `run.bat correlation-breakdown` | Yahoo Finance (1yr daily history + VIX) |
| **Sales Analytics BI Expert** | `run.bat sales-analytics` | Yahoo Finance retail proxies + dashboard |
| **Market Predictor** | `run.bat market-predictor` | Fuses all agent outputs into multi-horizon predictions |
| **Data Steward Expert** | `run.bat data-steward` | Platform catalog, output/ artifacts, health checks |
| **Records Management Expert** | `run.bat records-management` | Archive inventory, retention, snapshot archiving |
| **Meteorology Expert** | `run.bat meteorology` | [weather.gov](https://www.weather.gov/) / NWS API |

## Quick start

```bat
run.bat electricity
run.bat grid
run.bat transportation
run.bat patents
run.bat events
run.bat datascience
run.bat finance
run.bat financial-data
run.bat markets
run.bat geopolitics
run.bat logistics
run.bat theoretical-probability
run.bat empirical-probability
run.bat combined-conditional
run.bat research-statistics
run.bat correlation-breakdown
run.bat sales-analytics
run.bat market-predictor -o output/market_predictions.json
run.bat data-steward
run.bat records-management
run.bat meteorology
```

Or with options:

```bat
run.bat electricity -o output/electricity.json
run.bat grid -o output/grid.json
run.bat transportation -o output/transportation.json
run.bat patents -o output/patents.json
run.bat events -o output/world_events.json
run.bat finance -o output/finance.json
run.bat geopolitics --json
```

## EIA Grid Monitor Analyst

Civil/electrical engineering analysis of the [EIA Grid Monitor electric overview](https://www.eia.gov/electricity/gridmonitor/dashboard/electric_overview/US48/US48) for the U.S. lower 48 (US48):

- Hourly **demand** and **net generation** from EIA RTO region-data API
- **Fuel-type mix** (coal, gas, nuclear, solar, wind, hydro) from EIA fuel-type-data API
- ISO demand breakdown for Texas (ERCOT), California (CAISO), PJM, MISO, and NYISO
- Grid balance score, supply-demand gap, and electrical assessment
- Calibrated proxy fallback when the EIA API is unavailable or rate-limited
- Optional `eia_api_key` in `config.json` for live EIA Open Data API v2 access

Outputs:

- `output/electricity.json` — full analysis with market signals and recommendations
- `output/eia_grid_monitor_views.json` — dashboard view catalog

## Electrical Grid Analyst

Civil/electrical engineering analysis of live wholesale power markets from [Grid Status Live](https://www.gridstatus.io/live):

- **9 ISO/RTO markets** cataloged (ERCOT, CAISO, PJM, MISO, SPP, NYISO, ISO-NE, IESO, AESO)
- Live fuel mix from ERCOT and CAISO public dashboards
- Hourly regional demand from EIA RTO API
- CAISO net demand and battery dispatch visibility
- Grid stress score, renewable index, and electrical assessment
- Optional `gridstatus_api_key` for hub LMP pricing via [Grid Status API](https://www.gridstatus.io/)

## Civil Transportation Analyst

Civil engineering analysis of U.S. DOT open data from [data.transportation.gov](https://data.transportation.gov/):

- **10 DOT resource categories** cataloged (bridges, roadways, rail, transit, trucking, maritime)
- Railroad bridge inventory by state and design type (FRA dataset)
- Weekly traffic volume trends — passenger vs. truck demand
- FHWA commercial vehicle inspection volume by state
- Infrastructure stress score, freight momentum, and civil assessment
- Sector signals for rails, freight, and construction materials

## Patent Landscape Analyst

Tracks global patent databases, APIs, and monitoring resources while surfacing recent innovation activity:

- **16 patent resources** cataloged (USPTO ODP, PatentsView, Espacenet, PATENTSCOPE, Google Patents, Lens.org, etc.)
- Resource health checks (online / restricted / offline)
- Live innovation signals from OpenAlex, IPWatchdog, and USPTO trademark feed
- Sector classification: semiconductor, AI, biotech, energy, automotive, telecom
- Innovation velocity score and sector market signals

Optional: copy `config.example.json` to `config.json` and set `uspto_api_key` from [data.uspto.gov](https://data.uspto.gov/) for live US application search.

## World Events Tracker

Two ways to track global events that impact financial markets:

### Web app

Open `index.html` in any modern browser (or run `open_tracker.bat`). No build step or server required.

- **Add events** with title, date, region, category, impact level, and notes
- **Categories**: Geopolitical, Economic, Monetary Policy, Trade, Energy, Natural Disaster, Pandemic/Health, Technology, Other
- **Impact levels**: Critical, High, Medium, Low — colour-coded for quick scanning
- **Filter** by category, impact, or free-text search
- **Import JSON** from the Python agent (`output/world_events_tracker.json`)
- **Persistent** — events are saved to browser `localStorage`

### Python agent

Fetches live headlines from BBC World and NPR, classifies each event by category, region, and market impact, and exports JSON reports:

```bat
run.bat events -o output/world_events.json
```

Outputs:

- `output/world_events.json` — full analysis with market signals and recommendations
- `output/world_events_tracker.json` — web-import format for `index.html`

## Data Science Expert

Quantitative factor analysis on 10 US ETFs (SPY, QQQ, IWM, sectors, GLD, TLT, HYG):

- 20-day volatility, z-scores, and momentum factors
- Empirical P(up) from 60-session history
- Monte Carlo 5-day forward simulation (5,000 GBM paths)
- SPY correlation structure across factors
- Mean-reversion and momentum signals

## Google Finance Beta Analyst

Mathematician/trader analysis of [Google Finance Beta](https://www.google.com/finance/beta):

- **Equity sectors** (SIXB–SIXY) mapped to SPDR sector ETFs
- **US indices** — Dow, S&P 500, Nasdaq, Russell, VIX
- **Futures & crypto** — Dow/ES/NQ, gold, crude, BTC/ETH/SOL
- **Most active** stocks and day gainers/losers
- Mathematical opportunity scoring (momentum, dispersion, z-scores)
- Ranked trading setups: momentum continuation, mean reversion, swing trades
- Calibrated proxy fallback when live quotes are unavailable

```bat
run.bat finance -o output/finance.json
```

Outputs:

- `output/finance.json` — full analysis with trading opportunities and market signals
- `output/google_finance_views.json` — dashboard view catalog

## Yahoo Finance Statistical Analyst

Mathematician/market analyst statistical analysis of [Yahoo Finance](https://finance.yahoo.com/):

- **Cross-sectional statistics** — mean, median, σ, skewness, and kurtosis of sector returns
- **Breadth metrics** — advance/decline ratio from gainers/losers, % sectors positive
- **Sector z-scores** — relative performance vs peer distribution (distinct from time-series z)
- **3-month correlation matrix** among SPDR sector ETFs
- **Beta estimates** vs SPY and 20-day realized volatility regime
- **Statistical outlier detection** on Yahoo top movers (mover z-scores)
- **Linear trend regression** on S&P 500 (slope and R²)
- Statistical regime labels and mathematical edge assessment

```bat
run.bat financial-data -o output/financial_data.json
```

Outputs:

- `output/financial_data.json` — full statistical analysis with market signals
- `output/yahoo_finance_views.json` — Yahoo Finance dashboard view catalog

## Market Analyst Expert

Live US market analysis from Yahoo Finance:

- Major indices (^GSPC, ^DJI, ^IXIC, ^RUT) and VIX
- 11 sector ETFs with day and 1-week performance ranking
- Top 10 day gainers/losers and trending tickers
- Risk-on/risk-off regime, breadth, momentum, and style tilt (QQQ vs IWM)

## Geopolitics Expert

Monitors global headlines and scores risk across six theaters:

- **Ukraine / Russia**, **Middle East**, **China / Taiwan**
- **Trade / Sanctions**, **Energy Security**, **Americas**

Outputs:

- Global risk and escalation indices from live news classification
- Theater-level risk scores with top headlines
- Sector signals (defense, gold, oil, treasuries, semiconductors, EM)

## Logistics Expert

Evaluates logistics strategies from [MarineTraffic](https://www.marinetraffic.com/) AIS patterns across three global trade corridors:

- **North Sea / English Channel** (primary) — [MarineTraffic view](https://www.marinetraffic.com/en/ais/home/centerx:2.7/centery:51.2/zoom:6) — Rotterdam, Antwerp, Dover
- **US West Coast** — LA/Long Beach, Oakland
- **Singapore Strait** — Asia export chokepoint

Outputs:

- Marine traffic strategy evaluation (routing, anchorage, freight mix, port priority)
- Lane density, freight momentum, and port congestion scores
- Chokepoint, container backlog, retail lead-time, and manufacturing flow signals
- Sector signals (dry bulk, container shipping, retail, tankers, freight brokers)

```bat
run.bat logistics -o output/logistics.json
```

Writes:

- `output/logistics.json` — full analysis with market signals and recommendations
- `output/marine_traffic_corridors.json` — corridor dashboard catalog

Optional: copy `config.example.json` to `config.json` and set `marinetraffic_api_key` for live AIS data.

## Theoretical Probability Expert

Expert in theoretical probability applied to US market data:

- **Markov chain** — 3-state (bull/bear/neutral) transition matrix and 1-step forecast
- **Bayesian inference** — posterior regime probabilities updated with return and breadth evidence
- **Conditional probability** — P(sector up | SPY up/down), P(VIX up | SPY down), etc.
- **Binomial streak model** — theoretical vs empirical consecutive up/down streaks
- **GBM barrier probability** — first-passage risk of −5% drawdown within 5 days
- **Expected value & Kelly criterion** — EV and optimal sizing for momentum/mean-reversion bets
- **Law of large numbers** — sample size guidance for win-rate precision

```bat
run.bat theoretical-probability -o output/theoretical_probability.json
```

Outputs:

- `output/theoretical_probability.json` — full probability analysis with market signals
- `output/probability_models.json` — catalog of theoretical models and formulas

## Empirical Probability Expert

Expert in empirical (experimental) probability applied to US market data:

- **Observed frequencies** — empirical P(up/down) with trial counts
- **Wilson score 95% CI** — confidence intervals for win-rate estimates
- **Rolling win rates** — 20/60/120-day empirical probabilities
- **Conditional frequencies** — P(up | prior up/down), P(up | 2 down days)
- **Return-bin histogram** — empirical probability mass across move sizes
- **Bootstrap resampling** — non-parametric CI for win rate and mean return
- **Rule experiments** — momentum and mean-reversion trials with 70/30 train/test validation

```bat
run.bat empirical-probability -o output/empirical_probability.json
```

Outputs:

- `output/empirical_probability.json` — full empirical analysis with market signals
- `output/empirical_experiments.json` — catalog of experimental methods

## Combined & Conditional Probability Expert

Expert in combined and conditional probabilities applied to US market data:

- **Joint probability** P(A∩B) — same-day co-occurrence of market events
- **Union probability** P(A∪B) — at least one event occurs
- **Conditional probability** P(A|B) — sector/index moves given benchmark state
- **Multi-condition** P(A|B∩C) — e.g., P(Tech up | SPY up AND VIX down)
- **Independence tests** — compare P(A∩B) vs P(A)·P(B)
- **Chain rule** — decompose P(A∩B∩C) = P(A)·P(B|A)·P(C|A∩B)
- **Combined scenarios** — ranked multi-asset outcome probabilities

```bat
run.bat combined-conditional -o output/combined_conditional.json
```

Outputs:

- `output/combined_conditional.json` — full combined/conditional analysis
- `output/probability_concepts.json` — probability concepts and formulas catalog

## Research Statistics Expert

Research scientist / statistician analysis of US market return data:

- **One-sample t-test** — H₀: mean daily return = 0
- **Two-sample t-test** — compare asset vs SPY mean returns
- **95% confidence intervals** — for expected daily returns
- **OLS regression** — α, β, R² vs SPY with slope significance
- **Lag-1 autocorrelation** — momentum vs mean-reversion serial dependence
- **Jarque-Bera normality test** — skewness and kurtosis diagnostics
- **F-test** — equal variance comparison vs benchmark
- **Research findings** — ranked significant results at α = 0.05

```bat
run.bat research-statistics -o output/research_statistics.json
```

Outputs:

- `output/research_statistics.json` — full statistical research report
- `output/statistical_methods.json` — methods and formulas catalog

## Correlation Breakdown / Tail-Risk Expert

Quantitative risk analyst covering "correlation breakdown" — the tendency of historically
uncorrelated assets to converge toward r ≈ 1.0 during systemic liquidity shocks, eliminating
diversification benefits exactly when they are needed most ([Ray Dalio: surviving market
crashes](https://www.investopedia.com/ray-dalio-on-surviving-market-crashes-11699830)):

- **Calm vs stress correlation** — pairwise correlation to SPY in normal vs worst-tail return
  days, flagging convergence toward r ≈ 1.0 (a copula lower-tail-dependence proxy)
- **CVaR / Expected Shortfall** — historical-simulation VaR95, CVaR95, and CVaR99 per asset
- **Fat-tail diagnostics** — excess kurtosis flags where Gaussian VaR understates crash risk
- **Regime-switching proxy** — two-state (calm/panicked) VIX-driven Markov regime with
  empirical persistence and calm→panic switch probability
- **Portfolio protection playbook** — long volatility options, trend-following/CTA, and
  tail-risk budgeting strategies

```bat
run.bat correlation-breakdown -o output/correlation_breakdown.json
```

Outputs:

- `output/correlation_breakdown.json` — full correlation-breakdown and tail-risk report
- `output/tail_risk_frameworks.json` — copula/CVaR/regime-switching framework and protection-strategy catalog

## Sales Analytics BI Expert

Business Intelligence analysis of US retail and consumer sales proxies:

- **15 retail tickers** — Walmart, Costco, Amazon, Home Depot, Nike, and more
- **Category breakdown** — big box, e-commerce, restaurants, apparel, home improvement
- **BI KPIs** — sales momentum index, retail breadth, discretionary vs staples premium
- **Consumer strength score** — composite demand signal
- **Interactive dashboard** — KPI cards, category bars, ticker table, sparklines, signals

```bat
run.bat sales-analytics -o output/sales_analytics.json
open_sales_dashboard.bat
```

Outputs:

- `output/sales_analytics.json` — full BI analysis with market signals
- `output/sales_dashboard_data.json` — dashboard feed (auto-loaded by `sales_dashboard.html`)
- `output/sales_dashboard_panels.json` — dashboard panel catalog

## Data Steward Expert

Expert data stewardship and management for the Finance intelligence platform:

- **Data catalog** — 8 external sources with refresh policies and SLA metadata
- **Agent registry** — 17 agents with lineage (source → agent → output)
- **Health checks** — live endpoint monitoring (Yahoo Finance, OpenAlex, BBC RSS, NWS)
- **Artifact validation** — schema, completeness, and freshness of `output/*.json`
- **Stewardship issues** — severity-ranked gaps with remediation steps
- **Governance** — config.json key audit and data quality scoring

```bat
run.bat data-steward -o output/data_steward.json
```

Outputs:

- `output/data_steward.json` — full stewardship report with market signals
- `output/data_catalog.json` — data source catalog
- `output/data_lineage.json` — agent registry and lineage map

## Records Management Expert

Expert records manager / archivist for the Finance intelligence platform:

- **Archive inventory** — SHA-256 checksums, classification, and integrity verification
- **Retention schedule** — policy by record series (reports, catalogs, dashboard feeds)
- **Disposition actions** — retain, archive, dispose, and quarantine recommendations
- **Snapshot archiving** — timestamped copies to `output/archive/snapshots/` with manifest
- **Compliance scoring** — retention adherence and archive coverage metrics

```bat
run.bat records-management -o output/records_management.json
```

Outputs:

- `output/records_management.json` — full archivist report with market signals
- `output/archive_catalog.json` — inventory of all output records
- `output/retention_schedule.json` — retention and disposition policies
- `output/archive/snapshots/YYYYMMDD_HHMMSS/` — point-in-time archive snapshot

## Meteorology Expert

Analyzes US weather hazards and hub forecasts:

- Active NWS alerts (heat, cold, severe, flood, fire, wind)
- Synoptic assessment (season context, ridge/trough, tropical, agriculture, aviation)
- Stress scores for energy demand and market disruption
- Sector signals (utilities, nat gas, agriculture, insurance, refining)

## Market Predictor

Fuses signals from all Finance agents into ranked, multi-horizon market predictions:

- **6 prediction horizons** — `1m`, `1h`, `24h`, `1wk`, `1mo`, `1yr`
- **Accuracy-weighted fusion** — blends markets, finance, datascience, financial-data, geopolitics, sales-analytics
- **Per-ticker ranking** — predicted direction (up/down/flat), predicted return %, and confidence
- **Rationale** — sourced from composite agent signals and notes

### Standalone run

```bat
run.bat market-predictor -o output/market_predictions.json
open_market_predictions_dashboard.bat
```

Run the underlying data agents first so the predictor has signals to fuse:

```bat
run.bat markets
run.bat finance
run.bat datascience
run.bat financial-data
run.bat geopolitics
run.bat sales-analytics
run.bat market-predictor -o output/market_predictions.json
```

Outputs:

- `output/market_predictions.json` — ranked mover predictions per horizon

### Continuous predictions loop

`run_market_predictor_loop.py` re-runs the signal agents and fuses predictions on a
configurable interval (default 30 minutes). It logs progress to
`output/history/market_predictor_loop.log` and saves state to
`output/history/market_predictor_loop_state.json`.

```bat
REM Double-click to start:
Start Market Predictor Loop.bat

REM Or run directly:
python run_market_predictor_loop.py --interval-minutes 15
python run_market_predictor_loop.py --once
```

Press **Ctrl+C** (or send SIGTERM) to stop cleanly after the current cycle completes.

### Predictions dashboard

Open `market_predictions_dashboard.html` in any browser (or double-click
`open_market_predictions_dashboard.bat`) for a live, tab-per-horizon table of top
predicted gainers and losers with sortable columns and color-coded rows.

```bat
open_market_predictions_dashboard.bat
```

## Constant Backtesting

Every full pipeline cycle already scores a walk-forward backtest
(`historical_simulation.run_accuracy_benchmark`) and feeds the results into
`output/history/agent_learning.json`, so agents learn from the past to predict the
future. `run_backtest_loop.py` lets that backtest run continuously and
independently of the full pipeline — useful when you just want agents to keep
re-scoring their historical predictions on a set cadence.

It re-runs the walk-forward accuracy benchmark on a configurable interval
(default 60 minutes), rebuilding agent learning after every cycle. It logs
progress to `output/history/backtest_loop.log` and saves state to
`output/history/backtest_loop_state.json`.

```bat
REM Double-click to start:
Start Backtest Loop.bat

REM Or run directly:
python run_backtest_loop.py --interval-minutes 30
python run_backtest_loop.py --once
python run_backtest_loop.py --target-trials 2000 --max-symbols 60
```

Press **Ctrl+C** (or send SIGTERM) to stop cleanly after the current cycle completes.

Outputs:

- `output/history/accuracy_benchmark.json` — walk-forward backtest report
- `output/history/agent_learning.json` — adaptive bias/confidence learned from the backtest

## Requirements

- Python 3.10+
- `requests`