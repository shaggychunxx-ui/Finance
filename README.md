# Finance

Intelligence agents for financial market analysis. Each agent pulls live public data and produces expert summaries with sector signals.

## Agents

| Agent | Command | Data source |
|-------|---------|-------------|
| **Logistics Expert** | `run.bat logistics` | [MarineTraffic](https://www.marinetraffic.com/) AIS (optional key) |
| **Meteorology Expert** | `run.bat meteorology` | [weather.gov](https://www.weather.gov/) / NWS API |

## Quick start

```bat
run.bat logistics
run.bat meteorology
```

Or with options:

```bat
run.bat logistics --json
run.bat logistics -o output/logistics.json
```

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