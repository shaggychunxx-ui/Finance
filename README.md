# Finance

Intelligence agents for financial market analysis. Each agent pulls live public data and produces expert summaries with sector signals.

## Agents

| Agent | Command | Data source |
|-------|---------|-------------|
| **Meteorology Expert** | `run.bat` or `python main.py meteorology` | [weather.gov](https://www.weather.gov/) / NWS API |

## Quick start

```bat
run.bat
```

Or with options:

```bat
run.bat --json
run.bat -o output/meteorology.json
```

## Meteorology Expert

Analyzes US weather hazards and hub forecasts:

- Active NWS alerts (heat, cold, severe, flood, fire, wind)
- Synoptic assessment (season context, ridge/trough, tropical, agriculture, aviation)
- Stress scores for energy demand and market disruption
- Sector signals (utilities, nat gas, agriculture, insurance, refining)

Optional: copy `config.example.json` to `config.json` to customize forecast hubs.

## Requirements

- Python 3.10+
- `requests`