"""
Portfolio & Fund Manager Agent
==============================
Aggregates market signals and recommendations produced by every other Finance
repo agent into a single paper-trading portfolio. Starts from a $10,000 cash
balance, sizes short-term / mid-term / long-term positions, and simulates
realistic trading costs — a brokerage/slippage fee, an SEC Section 31 fee on
sells, and short-term vs. long-term capital-gains tax on realized profits.

The tradable universe spans multiple asset classes — broad-market and sector
equity ETFs, precious-metals ETFs (e.g. gold, silver), and bond/fixed-income
ETFs (Treasuries and investment-grade corporates) — each tagged with an
``asset_class`` for reporting. Dividend/interest income paid by held
positions (equity dividends, bond coupon income, ETF distributions) is
accrued pro-rata each run, taxed, and added to cash, so total return reflects
both price appreciation and income. Options and other derivatives are out of
scope: they require separate margin, expiry, and Greeks modeling that this
spot/ETF paper-trading ledger does not support.

No real funds are ever used. This agent only reads public market data and
maintains its own JSON ledger (``output/portfolio_state.json``) across runs.

Data: Yahoo Finance chart API (with calibrated proxy fallback) for prices,
plus the ``market_signals`` / ``recommendations`` emitted by every other
agent in ``agents/`` (via their public ``run_*_analysis`` entry points).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from agents.combined_conditional import run_combined_conditional_analysis
from agents.data_steward import run_data_steward_analysis
from agents.datascience import run_datascience_analysis
from agents.electricity import run_electricity_analysis
from agents.empirical_probability import run_empirical_probability_analysis
from agents.events import run_events_analysis
from agents.finance import run_finance_analysis
from agents.financial_data import run_financial_data_analysis
from agents.geopolitics import run_geopolitics_analysis
from agents.grid import run_grid_analysis
from agents.logistics import run_logistics_analysis
from agents.markets import run_markets_analysis
from agents.meteorology import run_meteorology_analysis
from agents.patents import run_patents_analysis
from agents.records_management import run_records_management_analysis
from agents.research_statistics import run_research_statistics_analysis
from agents.sales_analytics import run_sales_analytics_analysis
from agents.theoretical_probability import run_theoretical_probability_analysis
from agents.transportation import run_transportation_analysis

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Portfolio-Manager/1.0 (shaggychunxx@gmail.com)"}

# Every other agent in the repo — consulted for market_signals/recommendations.
SOURCE_AGENTS: dict[str, Callable[..., dict[str, Any]]] = {
    "combined-conditional": run_combined_conditional_analysis,
    "data-steward": run_data_steward_analysis,
    "datascience": run_datascience_analysis,
    "electricity": run_electricity_analysis,
    "empirical-probability": run_empirical_probability_analysis,
    "events": run_events_analysis,
    "finance": run_finance_analysis,
    "financial-data": run_financial_data_analysis,
    "geopolitics": run_geopolitics_analysis,
    "grid": run_grid_analysis,
    "logistics": run_logistics_analysis,
    "markets": run_markets_analysis,
    "meteorology": run_meteorology_analysis,
    "patents": run_patents_analysis,
    "records-management": run_records_management_analysis,
    "research-statistics": run_research_statistics_analysis,
    "sales-analytics": run_sales_analytics_analysis,
    "theoretical-probability": run_theoretical_probability_analysis,
    "transportation": run_transportation_analysis,
}

STARTING_BALANCE = 10_000.00
STATE_FILENAME = "portfolio_state.json"

# Trading cost assumptions (paper trading, but modeled on real-world costs).
TRADING_FEE_PCT = 0.0010     # 10 bps brokerage / execution slippage fee (buy + sell)
SEC_FEE_PCT = 0.0000278      # SEC Section 31 fee, charged on sell notional only
SHORT_TERM_TAX_RATE = 0.24   # realized gains held < 365 days, taxed as ordinary income
LONG_TERM_TAX_RATE = 0.15    # realized gains held >= 365 days, preferential rate
LONG_TERM_HOLDING_DAYS = 365

# Position sizing / rebalancing rules.
MAX_POSITION_WEIGHT = 0.20     # no single symbol above 20% of total portfolio value
MIN_CASH_RESERVE_PCT = 0.05    # always keep >=5% of portfolio value in cash
MIN_TRADE_NOTIONAL = 50.0      # skip dust-sized trades
BUY_CONVICTION_THRESHOLD = 0.34
SELL_CONVICTION_THRESHOLD = -0.34
MIN_AGENT_VOTES = 2            # require at least 2 agents to agree before buying

HORIZON_TARGET_WEIGHTS: dict[str, float] = {
    "short_term": 0.25,
    "mid_term": 0.35,
    "long_term": 0.40,
}

BOND_ETFS = {"TLT", "AGG", "LQD", "SHY"}
PRECIOUS_METAL_ETFS = {"GLD", "SLV"}
LONG_TERM_CORE = {"SPY", "QQQ", "IWM"} | BOND_ETFS | PRECIOUS_METAL_ETFS
SECTOR_ETFS = {"XLK", "XLE", "XLU", "XLF", "XLI", "XLY", "XLP", "XLRE", "XLV", "XLB", "XLC"}
NOT_TRADABLE = {"^VIX", "^GSPC", "^DJI", "^IXIC", "^RUT"}

SYMBOL_NAMES: dict[str, str] = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000",
    "GLD": "Gold", "SLV": "Silver",
    "TLT": "20+ Year Treasuries", "AGG": "US Aggregate Bonds",
    "LQD": "Investment Grade Corporate Bonds", "SHY": "1-3 Year Treasuries",
    "XLK": "Technology", "XLE": "Energy", "XLU": "Utilities", "XLF": "Financials",
    "XLI": "Industrials", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
    "XLRE": "Real Estate", "XLV": "Health Care", "XLB": "Materials", "XLC": "Communication",
}

# Broad asset-class tag for each symbol, surfaced on positions/signals so the
# portfolio's diversification across equities, precious metals, and bonds is
# visible in the report. Anything not listed defaults to "equity_etf".
ASSET_CLASS: dict[str, str] = {
    "SPY": "equity_etf", "QQQ": "equity_etf", "IWM": "equity_etf",
    "GLD": "precious_metal_etf", "SLV": "precious_metal_etf",
    "TLT": "bond_etf", "AGG": "bond_etf", "LQD": "bond_etf", "SHY": "bond_etf",
    **{sym: "sector_etf" for sym in SECTOR_ETFS},
}

# Approximate blended annual dividend/interest yield paid out by each symbol
# (equity dividends, bond coupon income, ETF distributions). Used to accrue
# income into cash between runs; symbols not listed are assumed to pay none.
ANNUAL_YIELD_PCT: dict[str, float] = {
    "SPY": 1.3, "QQQ": 0.6, "IWM": 1.2,
    "GLD": 0.0, "SLV": 0.0,
    "TLT": 4.0, "AGG": 4.2, "LQD": 4.8, "SHY": 4.5,
    "XLK": 0.7, "XLE": 3.2, "XLU": 2.9, "XLF": 1.6, "XLI": 1.4,
    "XLY": 0.7, "XLP": 2.4, "XLRE": 3.4, "XLV": 1.5, "XLB": 1.7, "XLC": 0.8,
}
DIVIDEND_INTEREST_TAX_RATE = 0.15  # blended qualified-dividend / interest income tax rate

# Calibrated fallback quotes for symbols not covered elsewhere, used only when
# both the live fetch and the shared Google-Finance proxy table miss a symbol.
SUPPLEMENTAL_PROXY_QUOTES: dict[str, dict[str, float]] = {
    "SPY": {"price": 748.3, "day_chg_pct": 0.0, "week_chg_pct": 0.9},
    "QQQ": {"price": 610.4, "day_chg_pct": -0.3, "week_chg_pct": -0.1},
    "IWM": {"price": 239.7, "day_chg_pct": -0.55, "week_chg_pct": 0.2},
    "GLD": {"price": 391.6, "day_chg_pct": 0.62, "week_chg_pct": 1.1},
    "SLV": {"price": 34.8, "day_chg_pct": 0.45, "week_chg_pct": 1.4},
    "TLT": {"price": 87.4, "day_chg_pct": 0.35, "week_chg_pct": 0.6},
    "AGG": {"price": 98.6, "day_chg_pct": 0.10, "week_chg_pct": 0.3},
    "LQD": {"price": 108.9, "day_chg_pct": 0.12, "week_chg_pct": 0.4},
    "SHY": {"price": 82.1, "day_chg_pct": 0.02, "week_chg_pct": 0.1},
}


def _horizon_for(symbol: str) -> str:
    if symbol in LONG_TERM_CORE:
        return "long_term"
    if symbol in SECTOR_ETFS:
        return "mid_term"
    return "short_term"


def _asset_class_for(symbol: str) -> str:
    return ASSET_CLASS.get(symbol, "equity_etf")


def _today() -> date:
    return datetime.now(timezone.utc).date()


@dataclass
class Lot:
    quantity: float
    cost_basis: float
    opened_at: str

    def to_dict(self) -> dict[str, Any]:
        return {"quantity": self.quantity, "cost_basis": self.cost_basis, "opened_at": self.opened_at}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Lot":
        return Lot(quantity=d["quantity"], cost_basis=d["cost_basis"], opened_at=d["opened_at"])


@dataclass
class Position:
    symbol: str
    name: str
    horizon: str
    asset_class: str = "equity_etf"
    lots: list[Lot] = field(default_factory=list)

    @property
    def quantity(self) -> float:
        return sum(l.quantity for l in self.lots)

    @property
    def avg_cost(self) -> float:
        qty = self.quantity
        if qty <= 0:
            return 0.0
        return sum(l.quantity * l.cost_basis for l in self.lots) / qty

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "horizon": self.horizon,
            "asset_class": self.asset_class,
            "lots": [l.to_dict() for l in self.lots],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Position":
        return Position(
            symbol=d["symbol"],
            name=d.get("name", d["symbol"]),
            horizon=d.get("horizon") or _horizon_for(d["symbol"]),
            asset_class=d.get("asset_class") or _asset_class_for(d["symbol"]),
            lots=[Lot.from_dict(l) for l in d.get("lots", [])],
        )


@dataclass
class Trade:
    date: str
    symbol: str
    action: str
    quantity: float
    price: float
    notional: float
    fees: float
    tax: float
    realized_pl: float | None
    horizon: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": round(self.quantity, 6),
            "price": round(self.price, 4),
            "notional": round(self.notional, 2),
            "fees": round(self.fees, 2),
            "tax": round(self.tax, 2),
            "realized_pl": round(self.realized_pl, 2) if self.realized_pl is not None else None,
            "horizon": self.horizon,
            "reason": self.reason,
        }


@dataclass
class PortfolioState:
    cash: float
    positions: dict[str, Position]
    trade_log: list[Trade]
    realized_pl_total: float
    fees_paid_total: float
    taxes_paid_total: float
    starting_balance: float
    created_at: str
    income_received_total: float = 0.0
    income_tax_paid_total: float = 0.0
    last_income_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": round(self.cash, 2),
            "positions": {sym: p.to_dict() for sym, p in self.positions.items()},
            "trade_log": [t.to_dict() for t in self.trade_log],
            "realized_pl_total": round(self.realized_pl_total, 2),
            "fees_paid_total": round(self.fees_paid_total, 2),
            "taxes_paid_total": round(self.taxes_paid_total, 2),
            "starting_balance": self.starting_balance,
            "created_at": self.created_at,
            "income_received_total": round(self.income_received_total, 2),
            "income_tax_paid_total": round(self.income_tax_paid_total, 2),
            "last_income_date": self.last_income_date,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PortfolioState":
        created_at = d.get("created_at", datetime.now(timezone.utc).isoformat())
        return PortfolioState(
            cash=d.get("cash", STARTING_BALANCE),
            positions={sym: Position.from_dict(p) for sym, p in d.get("positions", {}).items()},
            trade_log=[],  # trade_log is historical; kept on disk, not replayed in memory
            realized_pl_total=d.get("realized_pl_total", 0.0),
            fees_paid_total=d.get("fees_paid_total", 0.0),
            taxes_paid_total=d.get("taxes_paid_total", 0.0),
            starting_balance=d.get("starting_balance", STARTING_BALANCE),
            created_at=created_at,
            income_received_total=d.get("income_received_total", 0.0),
            income_tax_paid_total=d.get("income_tax_paid_total", 0.0),
            last_income_date=d.get("last_income_date") or created_at[:10],
        )

    @staticmethod
    def new() -> "PortfolioState":
        created_at = datetime.now(timezone.utc).isoformat()
        return PortfolioState(
            cash=STARTING_BALANCE,
            positions={},
            trade_log=[],
            realized_pl_total=0.0,
            fees_paid_total=0.0,
            taxes_paid_total=0.0,
            starting_balance=STARTING_BALANCE,
            created_at=created_at,
            income_received_total=0.0,
            income_tax_paid_total=0.0,
            last_income_date=created_at[:10],
        )


class PortfolioManagerExpert:
    """Portfolio & Fund Manager — aggregates every agent's signals into a paper portfolio."""

    def __init__(self, output_dir: Path | None = None, delay_seconds: float = 0.0) -> None:
        self.output_dir = output_dir or Path("output")
        self.state_path = self.output_dir / STATE_FILENAME
        self.delay_seconds = delay_seconds
        self._price_cache: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------ state
    def _load_state(self) -> PortfolioState:
        if self.state_path.exists():
            try:
                return PortfolioState.from_dict(json.loads(self.state_path.read_text(encoding="utf-8")))
            except Exception:
                return PortfolioState.new()
        return PortfolioState.new()

    def _save_state(self, state: PortfolioState, full_trade_log: list[Trade]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = state.to_dict()
        payload["trade_log"] = [t.to_dict() for t in full_trade_log]
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_trade_log(self) -> list[Trade]:
        if not self.state_path.exists():
            return []
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8")).get("trade_log", [])
        except Exception:
            return []
        trades: list[Trade] = []
        for t in raw:
            trades.append(Trade(
                date=t["date"], symbol=t["symbol"], action=t["action"],
                quantity=t["quantity"], price=t["price"], notional=t["notional"],
                fees=t["fees"], tax=t["tax"], realized_pl=t.get("realized_pl"),
                horizon=t.get("horizon", "short_term"), reason=t.get("reason", ""),
            ))
        return trades

    # ------------------------------------------------------------------ prices
    def _fetch_live_price(self, symbol: str) -> dict[str, float] | None:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "5d"},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]
            meta = result["meta"]
            price = meta.get("regularMarketPrice")
            if price is None:
                return None
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            valid = [float(c) for c in closes if c is not None]
            day_chg = None
            if len(valid) >= 2:
                day_chg = round(((valid[-1] - valid[-2]) / valid[-2]) * 100, 2)
            return {"price": round(float(price), 2), "day_chg_pct": day_chg or 0.0}
        except Exception:
            return None

    def _proxy_price(self, symbol: str) -> dict[str, float]:
        from agents.finance.expert import PROXY_QUOTES as GOOGLE_PROXY_QUOTES

        proxy = SUPPLEMENTAL_PROXY_QUOTES.get(symbol) or GOOGLE_PROXY_QUOTES.get(symbol)
        if proxy:
            return {"price": proxy["price"], "day_chg_pct": proxy.get("day_chg_pct", 0.0)}
        return {"price": 100.0, "day_chg_pct": 0.0}

    def _price(self, symbol: str) -> dict[str, float]:
        if symbol in self._price_cache:
            return self._price_cache[symbol]
        quote = self._fetch_live_price(symbol) or self._proxy_price(symbol)
        time.sleep(self.delay_seconds)
        self._price_cache[symbol] = quote
        return quote

    # ------------------------------------------------------------------ signals
    def _collect_signals(self) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, Any]], list[str]]:
        """Run every source agent and tally bullish/bearish votes per ticker."""
        votes: dict[str, list[dict[str, str]]] = {}
        agent_status: list[dict[str, Any]] = []
        all_recommendations: list[str] = []

        for agent_key, runner in SOURCE_AGENTS.items():
            try:
                result = runner(output=None)
            except Exception as exc:
                agent_status.append({"agent": agent_key, "status": "error", "detail": str(exc)})
                continue

            signals = result.get("market_signals", []) or []
            recs = result.get("recommendations", []) or []
            agent_status.append({"agent": agent_key, "status": "ok", "signals_used": len(signals)})
            all_recommendations.extend(f"[{agent_key}] {r}" for r in recs[:2])

            for sig in signals:
                bias = sig.get("bias", "NEUTRAL")
                reason = sig.get("reason", "")
                for ticker in sig.get("tickers", []) or []:
                    votes.setdefault(ticker, []).append({
                        "agent": agent_key, "bias": bias, "reason": reason,
                    })

        return votes, agent_status, all_recommendations

    @staticmethod
    def _conviction(ticker_votes: list[dict[str, str]]) -> tuple[float, int]:
        bull = sum(1 for v in ticker_votes if v["bias"] == "BULLISH")
        bear = sum(1 for v in ticker_votes if v["bias"] == "BEARISH")
        total = len(ticker_votes)
        if total == 0:
            return 0.0, 0
        return round((bull - bear) / total, 3), total

    # ------------------------------------------------------------------ trading
    def _portfolio_value(self, state: PortfolioState) -> float:
        value = state.cash
        for sym, pos in state.positions.items():
            qty = pos.quantity
            if qty > 0:
                value += qty * self._price(sym)["price"]
        return value

    def _accrue_income(self, state: PortfolioState, trades: list[Trade]) -> float:
        """Accrue dividend/interest income paid by held positions since the last run.

        Income is pro-rated daily from each symbol's ``ANNUAL_YIELD_PCT`` against its
        current market value, taxed at ``DIVIDEND_INTEREST_TAX_RATE``, and deposited
        as cash — so equity dividends and bond coupon/interest income both contribute
        to total return, not just price appreciation.
        """
        today = _today()
        try:
            last_date = date.fromisoformat(state.last_income_date) if state.last_income_date else today
        except ValueError:
            last_date = today
        days_elapsed = (today - last_date).days
        if days_elapsed <= 0:
            return 0.0

        total_income = 0.0
        for sym, pos in state.positions.items():
            qty = pos.quantity
            annual_yield_pct = ANNUAL_YIELD_PCT.get(sym, 0.0)
            if qty <= 0 or annual_yield_pct <= 0:
                continue
            market_value = qty * self._price(sym)["price"]
            gross_income = market_value * (annual_yield_pct / 100.0) * (days_elapsed / 365.0)
            if gross_income <= 0:
                continue
            tax = gross_income * DIVIDEND_INTEREST_TAX_RATE
            net_income = gross_income - tax

            state.cash += net_income
            state.income_received_total += gross_income
            state.income_tax_paid_total += tax
            total_income += net_income

            trades.append(Trade(
                date=today.isoformat(), symbol=sym, action="INCOME", quantity=0.0,
                price=self._price(sym)["price"], notional=round(gross_income, 2),
                fees=0.0, tax=round(tax, 2), realized_pl=None, horizon=pos.horizon,
                reason=(
                    f"Dividend/interest income accrued over {days_elapsed} day(s) "
                    f"at {annual_yield_pct:.2f}% annual yield"
                ),
            ))

        state.last_income_date = today.isoformat()
        return total_income

    def _sell_position(
        self, state: PortfolioState, sym: str, pos: Position, price: float,
        horizon: str, reason: str, trades: list[Trade],
    ) -> None:
        qty = pos.quantity
        if qty <= 0:
            return
        notional = qty * price
        fees = notional * (TRADING_FEE_PCT + SEC_FEE_PCT)

        realized_pl = 0.0
        tax = 0.0
        today = _today()
        for lot in pos.lots:
            lot_gain = (price - lot.cost_basis) * lot.quantity
            realized_pl += lot_gain
            if lot_gain > 0:
                try:
                    opened = date.fromisoformat(lot.opened_at)
                    held_days = (today - opened).days
                except ValueError:
                    held_days = 0
                rate = LONG_TERM_TAX_RATE if held_days >= LONG_TERM_HOLDING_DAYS else SHORT_TERM_TAX_RATE
                tax += lot_gain * rate

        proceeds = notional - fees - tax
        state.cash += proceeds
        state.realized_pl_total += realized_pl
        state.fees_paid_total += fees
        state.taxes_paid_total += tax

        trades.append(Trade(
            date=today.isoformat(), symbol=sym, action="SELL", quantity=qty, price=price,
            notional=notional, fees=fees, tax=tax, realized_pl=realized_pl,
            horizon=horizon, reason=reason,
        ))
        del state.positions[sym]

    def _buy_position(
        self, state: PortfolioState, sym: str, name: str, price: float,
        horizon: str, notional: float, reason: str, trades: list[Trade],
    ) -> None:
        if notional < MIN_TRADE_NOTIONAL or price <= 0:
            return
        fees = notional * TRADING_FEE_PCT
        total_cost = notional + fees
        if total_cost > state.cash:
            # Solve notional + notional * fee_pct = cash so the trade fits available cash.
            notional = max(0.0, state.cash / (1 + TRADING_FEE_PCT))
            fees = notional * TRADING_FEE_PCT
            total_cost = notional + fees
            if notional < MIN_TRADE_NOTIONAL:
                return

        qty = notional / price
        state.cash -= total_cost
        state.fees_paid_total += fees

        pos = state.positions.setdefault(
            sym, Position(symbol=sym, name=name, horizon=horizon, asset_class=_asset_class_for(sym))
        )
        pos.lots.append(Lot(quantity=qty, cost_basis=price, opened_at=_today().isoformat()))

        trades.append(Trade(
            date=_today().isoformat(), symbol=sym, action="BUY", quantity=qty, price=price,
            notional=notional, fees=fees, tax=0.0, realized_pl=None,
            horizon=horizon, reason=reason,
        ))

    def _run_trading_cycle(
        self, state: PortfolioState, votes: dict[str, list[dict[str, str]]],
    ) -> tuple[list[Trade], list[dict[str, Any]]]:
        trades: list[Trade] = []

        signals_considered: list[dict[str, Any]] = []
        for ticker, ticker_votes in votes.items():
            if ticker in NOT_TRADABLE:
                continue
            conviction, count = self._conviction(ticker_votes)
            signals_considered.append({
                "symbol": ticker,
                "horizon": _horizon_for(ticker),
                "conviction": conviction,
                "agent_votes": count,
                "agents": sorted({v["agent"] for v in ticker_votes}),
            })
        signals_considered.sort(key=lambda s: -abs(s["conviction"]))

        # 0) Accrue dividend/interest income paid by current holdings since last run.
        self._accrue_income(state, trades)

        # 1) Sell any held position whose aggregated conviction has turned bearish.
        for sym in list(state.positions.keys()):
            pos = state.positions[sym]
            ticker_votes = votes.get(sym, [])
            conviction, count = self._conviction(ticker_votes)
            if count > 0 and conviction <= SELL_CONVICTION_THRESHOLD:
                price = self._price(sym)["price"]
                reason = f"Aggregated conviction {conviction:+.2f} across {count} agent signal(s) turned bearish"
                self._sell_position(state, sym, pos, price, pos.horizon, reason, trades)

        # 2) Buy bullish candidates, sized by horizon target weights and position caps.
        total_value = self._portfolio_value(state)
        cash_floor = total_value * MIN_CASH_RESERVE_PCT

        candidates = [
            s for s in signals_considered
            if s["conviction"] >= BUY_CONVICTION_THRESHOLD and s["agent_votes"] >= MIN_AGENT_VOTES
        ]
        for cand in candidates:
            sym = cand["symbol"]
            horizon = cand["horizon"]
            price = self._price(sym)["price"]
            if price <= 0:
                continue

            horizon_target = HORIZON_TARGET_WEIGHTS.get(horizon, 0.25) * total_value
            horizon_current = sum(
                p.quantity * self._price(s)["price"]
                for s, p in state.positions.items() if p.horizon == horizon
            )
            existing_qty = state.positions[sym].quantity if sym in state.positions else 0.0
            existing_value = existing_qty * price
            max_symbol_value = MAX_POSITION_WEIGHT * total_value

            room_in_horizon = horizon_target - horizon_current
            room_in_symbol = max_symbol_value - existing_value
            available_cash = max(0.0, state.cash - cash_floor)

            notional = min(room_in_horizon, room_in_symbol, available_cash)
            if notional < MIN_TRADE_NOTIONAL:
                continue

            name = SYMBOL_NAMES.get(sym, sym)
            reason = (
                f"Aggregated conviction {cand['conviction']:+.2f} across "
                f"{cand['agent_votes']} agent signal(s): {', '.join(cand['agents'])}"
            )
            self._buy_position(state, sym, name, price, horizon, notional, reason, trades)

        return trades, signals_considered

    # ------------------------------------------------------------------ report
    def _expert_summary(
        self, total_value: float, state: PortfolioState, trades: list[Trade],
        agent_status: list[dict[str, Any]],
    ) -> str:
        ok_agents = sum(1 for a in agent_status if a["status"] == "ok")
        total_return_pct = ((total_value - state.starting_balance) / state.starting_balance) * 100
        buys = sum(1 for t in trades if t.action == "BUY")
        sells = sum(1 for t in trades if t.action == "SELL")
        return (
            f"Paper portfolio at ${total_value:,.2f} ({total_return_pct:+.2f}% since inception "
            f"of ${state.starting_balance:,.2f}). Synthesized signals from {ok_agents}/{len(agent_status)} "
            f"Finance agents this run — executed {buys} buy(s) and {sells} sell(s). "
            f"Lifetime realized P&L ${state.realized_pl_total:,.2f}, fees paid ${state.fees_paid_total:,.2f}, "
            f"taxes paid ${state.taxes_paid_total:,.2f}, dividend/interest income "
            f"${state.income_received_total:,.2f} (${state.income_tax_paid_total:,.2f} tax)."
        )

    def analyze(self) -> dict[str, Any]:
        state = self._load_state()
        prior_trade_log = self._load_trade_log()

        votes, agent_status, all_recommendations = self._collect_signals()
        trades, signals_considered = self._run_trading_cycle(state, votes)

        total_value = self._portfolio_value(state)
        invested_value = total_value - state.cash

        positions_out: list[dict[str, Any]] = []
        allocation_by_horizon = {"short_term": 0.0, "mid_term": 0.0, "long_term": 0.0}
        allocation_by_asset_class: dict[str, float] = {}
        for sym, pos in state.positions.items():
            qty = pos.quantity
            if qty <= 0:
                continue
            price = self._price(sym)["price"]
            market_value = qty * price
            cost_basis_total = qty * pos.avg_cost
            unrealized_pl = market_value - cost_basis_total
            unrealized_pl_pct = (unrealized_pl / cost_basis_total * 100) if cost_basis_total > 0 else 0.0
            allocation_by_horizon[pos.horizon] = allocation_by_horizon.get(pos.horizon, 0.0) + market_value
            allocation_by_asset_class[pos.asset_class] = (
                allocation_by_asset_class.get(pos.asset_class, 0.0) + market_value
            )
            positions_out.append({
                "symbol": sym,
                "name": pos.name,
                "horizon": pos.horizon,
                "asset_class": pos.asset_class,
                "annual_yield_pct": ANNUAL_YIELD_PCT.get(sym, 0.0),
                "quantity": round(qty, 6),
                "avg_cost": round(pos.avg_cost, 4),
                "price": price,
                "market_value": round(market_value, 2),
                "unrealized_pl": round(unrealized_pl, 2),
                "unrealized_pl_pct": round(unrealized_pl_pct, 2),
                "weight_pct": round((market_value / total_value * 100) if total_value else 0.0, 2),
                "opened_at": min((l.opened_at for l in pos.lots), default=None),
            })
        positions_out.sort(key=lambda p: -p["market_value"])

        allocation_pct = {
            k: round((v / total_value * 100) if total_value else 0.0, 2)
            for k, v in allocation_by_horizon.items()
        }
        allocation_pct["cash"] = round((state.cash / total_value * 100) if total_value else 0.0, 2)
        allocation_by_asset_class_pct = {
            k: round((v / total_value * 100) if total_value else 0.0, 2)
            for k, v in allocation_by_asset_class.items()
        }

        full_trade_log = prior_trade_log + trades
        self._save_state(state, full_trade_log)

        top_signals = [
            {
                "sector": SYMBOL_NAMES.get(s["symbol"], s["symbol"]),
                "tickers": [s["symbol"]],
                "bias": "BULLISH" if s["conviction"] > 0 else "BEARISH" if s["conviction"] < 0 else "NEUTRAL",
                "reason": f"{s['agent_votes']} agent(s) agree, conviction {s['conviction']:+.2f}",
            }
            for s in signals_considered[:10]
        ]

        recommendations: list[str] = []
        income_trades = [t for t in trades if t.action == "INCOME"]
        trade_actions = [t for t in trades if t.action != "INCOME"]
        if trade_actions:
            for t in trade_actions:
                verb = "Bought" if t.action == "BUY" else "Sold"
                recommendations.append(
                    f"{verb} {t.quantity:.4f} {t.symbol} @ ${t.price:,.2f} "
                    f"(fees ${t.fees:.2f}, tax ${t.tax:.2f}) — {t.reason}"
                )
        else:
            recommendations.append("No trades triggered this run — holding current allocation.")
        if income_trades:
            income_total = sum(t.notional for t in income_trades)
            income_tax_total = sum(t.tax for t in income_trades)
            recommendations.append(
                f"Received ${income_total - income_tax_total:,.2f} net dividend/interest income "
                f"(${income_total:,.2f} gross, ${income_tax_total:,.2f} tax) across "
                f"{len(income_trades)} position(s)."
            )
        recommendations.extend(all_recommendations[:5])

        summary = self._expert_summary(total_value, state, trades, agent_status)

        return {
            "meta": {
                "agent": "Portfolio & Fund Manager",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "expert_summary": summary,
                "assumptions": {
                    "starting_balance": STARTING_BALANCE,
                    "trading_fee_pct": TRADING_FEE_PCT,
                    "sec_fee_pct": SEC_FEE_PCT,
                    "short_term_capital_gains_tax_pct": SHORT_TERM_TAX_RATE,
                    "long_term_capital_gains_tax_pct": LONG_TERM_TAX_RATE,
                    "long_term_holding_days": LONG_TERM_HOLDING_DAYS,
                    "max_position_weight_pct": MAX_POSITION_WEIGHT * 100,
                    "min_cash_reserve_pct": MIN_CASH_RESERVE_PCT * 100,
                    "dividend_interest_tax_pct": DIVIDEND_INTEREST_TAX_RATE * 100,
                },
                "agents_consulted": agent_status,
                "data_source": "Yahoo Finance (proxy-calibrated) + aggregated Finance repo agent signals",
                "state_file": str(self.state_path),
            },
            "metrics": {
                "cash": round(state.cash, 2),
                "invested_value": round(invested_value, 2),
                "total_value": round(total_value, 2),
                "starting_balance": state.starting_balance,
                "total_return_pct": round(
                    (total_value - state.starting_balance) / state.starting_balance * 100, 2
                ),
                "unrealized_pl": round(sum(p["unrealized_pl"] for p in positions_out), 2),
                "realized_pl_total": round(state.realized_pl_total, 2),
                "fees_paid_total": round(state.fees_paid_total, 2),
                "taxes_paid_total": round(state.taxes_paid_total, 2),
                "income_received_total": round(state.income_received_total, 2),
                "income_tax_paid_total": round(state.income_tax_paid_total, 2),
            },
            "allocation_by_horizon_pct": allocation_pct,
            "allocation_by_asset_class_pct": allocation_by_asset_class_pct,
            "positions": positions_out,
            "trades_this_run": [t.to_dict() for t in trades],
            "trade_history_count": len(full_trade_log),
            "signals_considered": signals_considered[:25],
            "market_signals": top_signals,
            "recommendations": recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        if output is not None:
            self.output_dir = output.parent
            self.state_path = self.output_dir / STATE_FILENAME
        result = self.analyze()
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def run_portfolio_analysis(output: Path | None = None) -> dict[str, Any]:
    return PortfolioManagerExpert().run(output=output)
