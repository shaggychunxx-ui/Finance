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
| **Market Analyst Expert** | `run.bat markets` | [Yahoo Finance](https://finance.yahoo.com/) API |
| **Geopolitics Expert** | `run.bat geopolitics` | BBC World / NPR RSS (+ optional GDELT) |
| **Logistics Expert** | `run.bat logistics` | [MarineTraffic](https://www.marinetraffic.com/) AIS (optional key) |
| **Meteorology Expert** | `run.bat meteorology` | [weather.gov](https://www.weather.gov/) / NWS API |
| **Cross-Agent Consensus Expert** | `run.bat consensus` | All agents above + [Yahoo Finance](https://finance.yahoo.com/) API |

## Quick start

```bat
run.bat electricity
run.bat grid
run.bat transportation
run.bat patents
run.bat events
run.bat datascience
run.bat markets
run.bat geopolitics
run.bat logistics
run.bat meteorology
run.bat consensus
```

Or with options:

```bat
run.bat electricity -o output/electricity.json
run.bat grid -o output/grid.json
run.bat transportation -o output/transportation.json
run.bat patents -o output/patents.json
run.bat events -o output/world_events.json
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

Monitors three global trade corridors and assesses supply-chain stress:

- **North Sea / English Channel** — Rotterdam, Antwerp, Dover
- **US West Coast** — LA/Long Beach, Oakland
- **Singapore Strait** — Asia export chokepoint

Outputs:

- Lane density, freight momentum, and port congestion scores
- Chokepoint, container backlog, retail lead-time, and manufacturing flow signals
- Sector signals (dry bulk, container shipping, retail, tankers, freight brokers)

Optional: copy `config.example.json` to `config.json` and set `marinetraffic_api_key` for live AIS data.

## Meteorology Expert

Analyzes US weather hazards and hub forecasts:

- Active NWS alerts (heat, cold, severe, flood, fire, wind)
- Synoptic assessment (season context, ridge/trough, tropical, agriculture, aviation)
- Stress scores for energy demand and market disruption
- Sector signals (utilities, nat gas, agriculture, insurance, refining)

## Cross-Agent Consensus Expert

Runs every agent above together to determine overall US market conditions and forecast the
top movers:

- Aggregates the Markets, Data Science, Geopolitics, Grid, Electricity, Meteorology,
  Logistics, Transportation, Patents, and World Events agents into a single weighted
  **market condition score** (Risk-On / Neutral / Risk-Off) with contributing factors
- Selects the **top 5 US market movers** (day gainers + losers) from the Markets agent
- Runs a Monte Carlo quantitative model per mover for **24-hour**, **1-month**, and
  **1-year** horizons, producing direction (UP/DOWN), probability of being up,
  expected return, and a 10th–90th percentile range
- Tilts each mover's forecast drift by the overall macro market-condition score, so a
  Risk-Off backdrop nudges predictions more bearish and vice versa
- Falls back to a lightweight heuristic prediction for movers with insufficient price history
- Per-agent status briefs (ok/error) and one-line takeaways from each contributing agent

## Requirements

- Python 3.10+
- `requests`