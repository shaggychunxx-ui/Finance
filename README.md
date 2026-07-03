# Finance

Intelligence agents for financial market analysis. Each agent pulls live public data and produces expert summaries with sector signals.

## Agents

| Agent | Command | Data source |
|-------|---------|-------------|
| **Data Science Expert** | `run.bat datascience` | Yahoo Finance (6mo daily history) |
| **Market Analyst Expert** | `run.bat markets` | [Yahoo Finance](https://finance.yahoo.com/) API |
| **Geopolitics Expert** | `run.bat geopolitics` | BBC World / NPR RSS (+ optional GDELT) |
| **Logistics Expert** | `run.bat logistics` | [MarineTraffic](https://www.marinetraffic.com/) AIS (optional key) |
| **Meteorology Expert** | `run.bat meteorology` | [weather.gov](https://www.weather.gov/) / NWS API |

## Quick start

```bat
run.bat datascience
run.bat markets
run.bat geopolitics
run.bat logistics
run.bat meteorology
```

Or with options:

```bat
run.bat geopolitics --json
run.bat geopolitics -o output/geopolitics.json
```

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

## Requirements

- Python 3.10+
- `requests`