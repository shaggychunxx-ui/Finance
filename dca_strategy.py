"""Dollar-Cost Averaging (DCA) — programmatic risk-mitigation strategy.

DCA deploys a fixed fiat amount into an asset at rigid chronological intervals,
decoupling execution price from localized market peaks. A fixed cash amount
naturally buys more shares when prices are low and fewer when prices are high,
which structurally lowers the volume-weighted cost basis relative to the
simple average price over the same period.

This module gives agents the programmatic building blocks to:
  - schedule and gate DCA deployments on a fixed interval (no market timing),
  - record each deployment (capital in, price, shares acquired),
  - compute the volume-weighted cost basis vs. the simple average price,
  - value the accumulated position and report net return.

State is persisted per-symbol/plan under output/dca/ so schedules survive
across pipeline cycles, mirroring the JSON-store pattern used by
sleeve_policy.py and trade_history.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

DCA_DIR = OUTPUT / "dca"

DEFAULT_INTERVAL_DAYS = 30.0

DEFAULT_DCA_POLICY = {
    "enabled": True,
    # Fixed fiat amount deployed each interval — never timed to "market conditions".
    "fixed_amount_usd": 1000.0,
    # Rigid chronological cadence in days (e.g. 7 = weekly, 30 ~= monthly).
    "interval_days": DEFAULT_INTERVAL_DAYS,
    # Require fractional share support so residual cash never sits uninvested.
    "allow_fractional_shares": True,
    # Reinvest dividends into additional shares of the same symbol (DRIP).
    "reinvest_dividends": True,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when
    except ValueError:
        return None


def _plan_path(symbol: str) -> Path:
    safe = str(symbol or "").strip().upper() or "UNKNOWN"
    return DCA_DIR / f"{safe}.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@dataclass
class DCADeployment:
    """A single fixed-amount deployment into an asset."""

    capital_usd: float
    price: float
    shares: float
    executed_at: str = field(default_factory=_now_iso)

    def as_dict(self) -> dict[str, Any]:
        return {
            "capital_usd": round(self.capital_usd, 2),
            "price": round(self.price, 6),
            "shares": round(self.shares, 8),
            "executed_at": self.executed_at,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "DCADeployment":
        return cls(
            capital_usd=float(row.get("capital_usd") or 0.0),
            price=float(row.get("price") or 0.0),
            shares=float(row.get("shares") or 0.0),
            executed_at=str(row.get("executed_at") or _now_iso()),
        )


@dataclass
class DCAPlan:
    """Fixed-interval accumulation plan for a single symbol."""

    symbol: str
    fixed_amount_usd: float = DEFAULT_DCA_POLICY["fixed_amount_usd"]
    interval_days: float = DEFAULT_DCA_POLICY["interval_days"]
    allow_fractional_shares: bool = True
    reinvest_dividends: bool = True
    deployments: list[DCADeployment] = field(default_factory=list)

    # -- persistence -----------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "fixed_amount_usd": round(self.fixed_amount_usd, 2),
            "interval_days": self.interval_days,
            "allow_fractional_shares": self.allow_fractional_shares,
            "reinvest_dividends": self.reinvest_dividends,
            "deployments": [d.as_dict() for d in self.deployments],
            "updated_at": _now_iso(),
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "DCAPlan":
        return cls(
            symbol=str(row.get("symbol") or "").strip().upper(),
            fixed_amount_usd=float(row.get("fixed_amount_usd") or DEFAULT_DCA_POLICY["fixed_amount_usd"]),
            interval_days=float(row.get("interval_days") or DEFAULT_DCA_POLICY["interval_days"]),
            allow_fractional_shares=bool(row.get("allow_fractional_shares", True)),
            reinvest_dividends=bool(row.get("reinvest_dividends", True)),
            deployments=[DCADeployment.from_dict(d) for d in (row.get("deployments") or [])],
        )

    # -- mechanics ---------------------------------------------------------
    @property
    def total_capital_usd(self) -> float:
        return round(sum(d.capital_usd for d in self.deployments), 2)

    @property
    def total_shares(self) -> float:
        return round(sum(d.shares for d in self.deployments), 8)

    @property
    def simple_average_price(self) -> float:
        """Unweighted mean of the deployment prices (not capital-weighted)."""
        if not self.deployments:
            return 0.0
        return round(sum(d.price for d in self.deployments) / len(self.deployments), 6)

    @property
    def volume_weighted_cost_basis(self) -> float:
        """Total capital deployed / total shares acquired — the true DCA cost basis."""
        shares = self.total_shares
        if shares <= 0:
            return 0.0
        return round(self.total_capital_usd / shares, 6)

    def last_deployment_at(self) -> datetime | None:
        if not self.deployments:
            return None
        return _parse_iso(self.deployments[-1].executed_at)

    def next_due_at(self) -> datetime | None:
        last = self.last_deployment_at()
        if last is None:
            return None
        return last + timedelta(days=self.interval_days)

    def is_due(self, *, as_of: datetime | None = None) -> bool:
        """Rigid chronological gate — no discretion, no market timing."""
        moment = as_of or _now()
        last = self.last_deployment_at()
        if last is None:
            return True
        return moment >= last + timedelta(days=self.interval_days)

    def deploy(
        self,
        price: float,
        *,
        capital_usd: float | None = None,
        executed_at: str | None = None,
    ) -> DCADeployment:
        """Convert a fixed fiat amount into shares at the given price."""
        px = float(price)
        if px <= 0:
            raise ValueError("price must be positive")
        amount = float(capital_usd) if capital_usd is not None else self.fixed_amount_usd
        if amount <= 0:
            raise ValueError("capital_usd must be positive")
        shares = amount / px
        if not self.allow_fractional_shares:
            shares = float(int(shares))
            if shares <= 0:
                raise ValueError(
                    "fixed_amount_usd is below one whole share price and fractional "
                    "shares are disabled; residual cash would sit uninvested"
                )
        deployment = DCADeployment(
            capital_usd=amount,
            price=px,
            shares=shares,
            executed_at=executed_at or _now_iso(),
        )
        self.deployments.append(deployment)
        return deployment

    def portfolio_value(self, current_price: float) -> float:
        return round(self.total_shares * float(current_price), 2)

    def net_return_pct(self, current_price: float) -> float:
        capital = self.total_capital_usd
        if capital <= 0:
            return 0.0
        gain = self.portfolio_value(current_price) - capital
        return round(gain / capital * 100.0, 4)

    def summary(self, current_price: float | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {
            "symbol": self.symbol,
            "deployments": len(self.deployments),
            "total_capital_usd": self.total_capital_usd,
            "total_shares": self.total_shares,
            "simple_average_price": self.simple_average_price,
            "volume_weighted_cost_basis": self.volume_weighted_cost_basis,
        }
        if current_price is not None:
            row["current_price"] = round(float(current_price), 6)
            row["portfolio_value_usd"] = self.portfolio_value(current_price)
            row["net_return_pct"] = self.net_return_pct(current_price)
        return row


def load_dca_policy(config_path: Path | None = None) -> dict[str, Any]:
    """Load global DCA defaults, optionally overridden by etrade_config.json."""
    settings = dict(DEFAULT_DCA_POLICY)
    path = config_path or (OUTPUT.parent / "etrade_config.json")
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        strategy = raw.get("strategy", {})
        block = strategy.get("dca", {}) if isinstance(strategy, dict) else {}
        if isinstance(block, dict):
            settings.update({k: block[k] for k in settings if k in block})
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def load_dca_plan(symbol: str) -> DCAPlan:
    symbol = str(symbol or "").strip().upper()
    row = _load_json(_plan_path(symbol))
    if row:
        return DCAPlan.from_dict(row)
    policy = load_dca_policy()
    return DCAPlan(
        symbol=symbol,
        fixed_amount_usd=float(policy["fixed_amount_usd"]),
        interval_days=float(policy["interval_days"]),
        allow_fractional_shares=bool(policy["allow_fractional_shares"]),
        reinvest_dividends=bool(policy["reinvest_dividends"]),
    )


def save_dca_plan(plan: DCAPlan) -> None:
    _write_json(_plan_path(plan.symbol), plan.as_dict())


def record_deployment(
    symbol: str,
    price: float,
    *,
    capital_usd: float | None = None,
    executed_at: str | None = None,
) -> dict[str, Any]:
    """Load a symbol's DCA plan, deploy fixed capital at ``price``, and persist it."""
    plan = load_dca_plan(symbol)
    plan.deploy(price, capital_usd=capital_usd, executed_at=executed_at)
    save_dca_plan(plan)
    return plan.summary(current_price=price)


def due_symbols(symbols: list[str], *, as_of: datetime | None = None) -> list[str]:
    """Rigid interval gate — which symbols are due for their next fixed deployment."""
    due: list[str] = []
    for symbol in symbols:
        plan = load_dca_plan(symbol)
        if plan.is_due(as_of=as_of):
            due.append(str(symbol or "").strip().upper())
    return due
