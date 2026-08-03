"""
Massive.com Market Data Agent
=============================
Pulls U.S. equity snapshots and previous-day OHLC from the Massive REST API
(https://api.massive.com) for a liquid watchlist. Complements Yahoo-backed
markets / financial-data agents with a dedicated vendor feed.

Auth (never commit secrets):
  1. Environment variable MASSIVE_API_KEY (preferred by Massive docs)
  2. etrade_config.json / config.json → data_apis.massive_api_key
  3. Top-level massive_api_key in those config files

Without a key the agent writes a structured report with status=no_api_key
and recommendations (does not crash the pipeline).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Massive-Market/1.0 (shaggychunxx@gmail.com)"}
API_BASE = "https://api.massive.com"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "output" / "massive_market.json"
DASHBOARD_URL = "https://massive.com/docs/rest/stocks/overview"

# Liquid core + sector proxies (Massive stocks tickers; no Yahoo-style ^ prefixes)
WATCHLIST: list[dict[str, str]] = [
    {"ticker": "SPY", "label": "S&P 500 ETF"},
    {"ticker": "QQQ", "label": "Nasdaq-100 ETF"},
    {"ticker": "IWM", "label": "Russell 2000 ETF"},
    {"ticker": "DIA", "label": "Dow Jones ETF"},
    {"ticker": "AAPL", "label": "Apple"},
    {"ticker": "MSFT", "label": "Microsoft"},
    {"ticker": "NVDA", "label": "NVIDIA"},
    {"ticker": "AMZN", "label": "Amazon"},
    {"ticker": "META", "label": "Meta"},
    {"ticker": "GOOGL", "label": "Alphabet"},
    {"ticker": "TSLA", "label": "Tesla"},
    {"ticker": "XLK", "label": "Tech sector"},
    {"ticker": "XLF", "label": "Financials sector"},
    {"ticker": "XLE", "label": "Energy sector"},
    {"ticker": "XLV", "label": "Health Care sector"},
]


@dataclass
class BarSnapshot:
    ticker: str
    label: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    vwap: float | None = None
    day_chg_pct: float | None = None
    timestamp_ms: int | None = None
    ok: bool = False
    error: str | None = None


@dataclass
class MassiveMarketReport:
    status: str
    source: str
    api_base: str
    has_api_key: bool
    watchlist_count: int
    bars: list[BarSnapshot] = field(default_factory=list)
    gainers: list[str] = field(default_factory=list)
    losers: list[str] = field(default_factory=list)
    assessment: dict[str, str] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    generated_at: str = ""


class MassiveMarketAnalyst(BaseExpert):
    def __init__(
        self,
        *,
        config_path: Path | None = None,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="massive-market")
        self.config = self._load_config(config_path)
        self.api_key = self._resolve_api_key(self.config)

    @staticmethod
    def _load_config(config_path: Path | None) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[2]
        # Prefer runtime stack when present (same pattern as FRED).
        runtime = Path.home() / "Finance"
        candidates = [
            config_path,
            runtime / "etrade_config.json",
            runtime / "config.json",
            root / "etrade_config.json",
            root / "config.json",
            root / "config" / "data_apis.example.json",
        ]
        merged: dict[str, Any] = {}
        for path in candidates:
            if path is None or not Path(path).is_file():
                continue
            try:
                raw = json.loads(Path(path).read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            apis = raw.get("data_apis") if isinstance(raw.get("data_apis"), dict) else {}
            for key in ("massive_api_key", "MASSIVE_API_KEY"):
                val = apis.get(key) or raw.get(key)
                if val and not merged.get("massive_api_key"):
                    merged["massive_api_key"] = str(val).strip()
        return merged

    @staticmethod
    def _resolve_api_key(config: dict[str, Any]) -> str:
        env = (os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY") or "").strip()
        if env:
            return env
        return str(config.get("massive_api_key") or "").strip()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("no_api_key")
        q = dict(params or {})
        q["apiKey"] = self.api_key
        url = f"{API_BASE}{path}"
        resp = requests.get(url, headers=HEADERS, params=q, timeout=30)
        if resp.status_code == 401:
            raise RuntimeError("unauthorized")
        if resp.status_code == 403:
            raise RuntimeError("forbidden_plan")
        if resp.status_code == 429:
            raise RuntimeError("rate_limited")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return {"status": "ERROR", "results": []}
        return data

    def _prev_day_bar(self, ticker: str, label: str) -> BarSnapshot:
        snap = BarSnapshot(ticker=ticker, label=label)
        try:
            data = self._get(f"/v2/aggs/ticker/{ticker}/prev", {"adjusted": "true"})
            results = data.get("results") or []
            if not results:
                snap.error = "empty_results"
                return snap
            row = results[0] if isinstance(results[0], dict) else {}
            o = _f(row.get("o"))
            c = _f(row.get("c"))
            snap.open = o
            snap.high = _f(row.get("h"))
            snap.low = _f(row.get("l"))
            snap.close = c
            snap.volume = _f(row.get("v"))
            snap.vwap = _f(row.get("vw"))
            snap.timestamp_ms = int(row["t"]) if row.get("t") is not None else None
            if o and c and o != 0:
                snap.day_chg_pct = round(100.0 * (c - o) / o, 3)
            snap.ok = c is not None
        except Exception as exc:
            snap.error = str(exc)[:120]
        return snap

    def _fetch_top_movers(self, direction: str) -> list[str]:
        """Best-effort gainers/losers; endpoint may require a paid plan."""
        try:
            # Stocks snapshot top movers (Massive / Polygon-style)
            data = self._get(f"/v2/snapshot/locale/us/markets/stocks/{direction}")
            tickers = data.get("tickers") or data.get("results") or []
            out: list[str] = []
            for item in tickers[:10]:
                if isinstance(item, dict):
                    t = item.get("ticker") or item.get("T")
                    if t:
                        out.append(str(t))
            return out
        except Exception:
            return []

    def analyze(self) -> MassiveMarketReport:
        now = datetime.now(timezone.utc).isoformat()
        report = MassiveMarketReport(
            status="ok",
            source="Massive REST API",
            api_base=API_BASE,
            has_api_key=bool(self.api_key),
            watchlist_count=len(WATCHLIST),
            generated_at=now,
        )
        if not self.api_key:
            report.status = "no_api_key"
            report.recommendations = [
                "Set MASSIVE_API_KEY env var (preferred) or data_apis.massive_api_key in runtime etrade_config.json",
                "Key lives at https://massive.com/dashboard/keys — never commit secrets to git",
                "After key is set, re-run pipeline quant lane or this agent alone",
            ]
            report.assessment = {
                "regime": "unknown",
                "note": "Massive API key not configured on this host",
            }
            return report

        bars: list[BarSnapshot] = []
        for item in WATCHLIST:
            if self.pipeline_should_skip_symbol(item["ticker"]):
                continue
            bars.append(self._prev_day_bar(item["ticker"], item["label"]))
            time.sleep(0.12)

        report.bars = bars
        ok_bars = [b for b in bars if b.ok and b.day_chg_pct is not None]
        errors = [f"{b.ticker}:{b.error}" for b in bars if b.error]
        report.errors = errors[:20]

        if not ok_bars:
            report.status = "api_error" if errors else "empty"
            report.recommendations.append(
                "Massive key present but no bars returned — check plan access / auth at dashboard"
            )
        else:
            ranked = sorted(ok_bars, key=lambda b: b.day_chg_pct or 0.0, reverse=True)
            report.gainers = [f"{b.ticker} {b.day_chg_pct:+.2f}%" for b in ranked[:5] if (b.day_chg_pct or 0) > 0]
            report.losers = [
                f"{b.ticker} {b.day_chg_pct:+.2f}%"
                for b in sorted(ok_bars, key=lambda b: b.day_chg_pct or 0.0)[:5]
                if (b.day_chg_pct or 0) < 0
            ]
            spy = next((b for b in ok_bars if b.ticker == "SPY"), None)
            mean_chg = sum(b.day_chg_pct or 0 for b in ok_bars) / max(1, len(ok_bars))
            if spy and spy.day_chg_pct is not None:
                if spy.day_chg_pct >= 0.5:
                    regime = "risk-on"
                elif spy.day_chg_pct <= -0.5:
                    regime = "risk-off"
                else:
                    regime = "mixed"
            else:
                regime = "mixed"
            report.assessment = {
                "regime": regime,
                "spy_day_chg_pct": f"{spy.day_chg_pct:+.3f}" if spy and spy.day_chg_pct is not None else "n/a",
                "watchlist_mean_day_chg_pct": f"{mean_chg:+.3f}",
                "bars_ok": str(len(ok_bars)),
            }
            if regime == "risk-on":
                report.recommendations.append("Massive feed: risk-on bias on liquid ETFs — favor long lean on strength")
            elif regime == "risk-off":
                report.recommendations.append("Massive feed: risk-off — tighten risk / prefer defensives")
            else:
                report.recommendations.append("Massive feed: mixed tape — wait for clearer breadth/confirmation")

        # Optional movers (ignore if plan blocks)
        movers_up = self._fetch_top_movers("gainers")
        movers_down = self._fetch_top_movers("losers")
        if movers_up:
            report.gainers = report.gainers or [f"{t}" for t in movers_up[:5]]
        if movers_down:
            report.losers = report.losers or [f"{t}" for t in movers_down[:5]]

        report.recommendations = self.append_memory_recommendations(report.recommendations)
        return report

    def to_dict(self, report: MassiveMarketReport) -> dict[str, Any]:
        payload = {
            "agent": "massive-market",
            "label": "Massive.com Market Data",
            "temperature": self.temperature,
            "status": report.status,
            "source": report.source,
            "api_base": report.api_base,
            "has_api_key": report.has_api_key,
            "generated_at": report.generated_at,
            "watchlist_count": report.watchlist_count,
            "assessment": report.assessment,
            "gainers": report.gainers,
            "losers": report.losers,
            "recommendations": report.recommendations,
            "errors": report.errors,
            "bars": [asdict(b) for b in report.bars],
            "dashboard": DASHBOARD_URL,
            "signal": {
                "direction": _direction_from_assessment(report.assessment),
                "confidence": 0.55 if report.status == "ok" else 0.15,
                "horizon": self.preferred_horizon() or "24h",
            },
        }
        try:
            from agent_groups import apply_group_conduct_to_report

            payload = apply_group_conduct_to_report(payload, "massive-market")
        except Exception:
            pass
        return payload

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        out = output or DEFAULT_OUTPUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _direction_from_assessment(assessment: dict[str, str]) -> str:
    regime = (assessment or {}).get("regime", "")
    if regime == "risk-on":
        return "BULLISH"
    if regime == "risk-off":
        return "BEARISH"
    return "NEUTRAL"


def run_massive_market_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return MassiveMarketAnalyst(pipeline_context=pipeline_context).run(output=output)
