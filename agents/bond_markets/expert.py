"""
Bond Markets & Fixed-Income Expert
==================================
Rates and credit sleeve specialist: Treasury curve shape (2s/10s proxy via SHY/IEF/TLT),
real yields (TIP), investment-grade and high-yield credit (LQD/HYG), aggregate bond
beta (BND/AGG), and duration risk playbooks for multi-asset books.

Domain expertise covered:
  - Duration / convexity intuition via long-bond vs short-bond relative returns
  - Curve steepener/flattener proxies (TLT vs SHY, IEF)
  - Credit risk-on/off (HYG vs LQD vs TLT flight-to-quality)
  - Inflation-linked (TIP) vs nominal Treasuries
  - Policy sensitivity: Fed hiking/cutting regimes and bond beta to equities

Data: Yahoo Finance daily closes for liquid bond ETFs (tradable proxies for the
cash bond market). Complements ``corporate-credit`` (HY OAS / CDS structure).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "output" / "bond_markets.json"
DASHBOARD_URL = "https://finance.yahoo.com/bonds/"

BOND_UNIVERSE: dict[str, dict[str, str]] = {
    "SHY": {"label": "1–3Y Treasuries", "bucket": "rates_short", "duration": "low"},
    "IEF": {"label": "7–10Y Treasuries", "bucket": "rates_intermediate", "duration": "medium"},
    "TLT": {"label": "20+Y Treasuries", "bucket": "rates_long", "duration": "high"},
    "TIP": {"label": "TIPS (real yield)", "bucket": "real_yield", "duration": "medium"},
    "BND": {"label": "US Aggregate Bond", "bucket": "aggregate", "duration": "medium"},
    "AGG": {"label": "US Aggregate Bond (iShares)", "bucket": "aggregate", "duration": "medium"},
    "LQD": {"label": "IG Corporate Bond", "bucket": "credit_ig", "duration": "medium"},
    "HYG": {"label": "High Yield Corporate", "bucket": "credit_hy", "duration": "low_med"},
    "JNK": {"label": "High Yield (SPDR)", "bucket": "credit_hy", "duration": "low_med"},
    "MUB": {"label": "Municipal Bond", "bucket": "muni", "duration": "medium"},
    "SGOV": {"label": "0–3M T-Bill", "bucket": "cash_like", "duration": "ultra_low"},
    "BIL": {"label": "1–3M T-Bill", "bucket": "cash_like", "duration": "ultra_low"},
}

BOND_PLAYBOOK: list[dict[str, str]] = [
    {
        "id": "duration_risk",
        "name": "Duration risk",
        "rule": "Long duration (TLT) thrives when yields fall; cut duration when yields rise or inflation re-accelerates.",
    },
    {
        "id": "curve_shape",
        "name": "Curve shape",
        "rule": "TLT outperforming SHY ≈ bull steepener/rally in long end; SHY > TLT ≈ rising long yields or bear steepener risk.",
    },
    {
        "id": "credit_spread",
        "name": "Credit spreads",
        "rule": "HYG outperforming LQD/TLT = risk-on credit; HYG lagging while TLT rises = flight-to-quality / spread stress.",
    },
    {
        "id": "real_yields",
        "name": "Real yields",
        "rule": "TIP vs IEF: TIP leadership = inflation premium; IEF leadership = disinflation / nominal rally.",
    },
    {
        "id": "liquidity_ladder",
        "name": "Liquidity ladder",
        "rule": "Use SGOV/BIL/SHY for ballast; size HYG as equity-like credit beta, not safe duration.",
    },
    {
        "id": "fed_path",
        "name": "Policy path",
        "rule": "Easing cycle: extend duration carefully; hiking / QT: prefer short end and floating/cash-like.",
    },
]


@dataclass
class BondSleeve:
    symbol: str
    label: str
    bucket: str
    duration: str
    last: float | None = None
    day_chg_pct: float | None = None
    week_chg_pct: float | None = None
    month_chg_pct: float | None = None
    score: float = 0.0
    notes: list[str] = field(default_factory=list)


class BondMarketsExpert(BaseExpert):
    def __init__(
        self,
        *,
        pipeline_context: dict[str, Any] | None = None,
        delay_seconds: float = 0.25,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="bond-markets")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _pct(closes: list[float], lookback: int) -> float | None:
        if len(closes) <= lookback or closes[-1 - lookback] == 0:
            return None
        return round((closes[-1] / closes[-1 - lookback] - 1.0) * 100.0, 3)

    def analyze(self) -> dict[str, Any]:
        closes_map: dict[str, list[float]] = {}
        errors: list[str] = []
        sleeves: list[BondSleeve] = []

        for sym, meta in BOND_UNIVERSE.items():
            if self.pipeline_should_skip_symbol(sym):
                continue
            try:
                closes = self.fetch_yahoo_closes(sym, range_="1y", interval="1d")
            except Exception as exc:
                errors.append(f"{sym}: {exc}")
                continue
            if len(closes) < 25:
                errors.append(f"{sym}: insufficient bars")
                continue
            closes_map[sym] = closes
            month = self._pct(closes, 21)
            week = self._pct(closes, 5)
            day = self._pct(closes, 1)
            score = 50.0
            if month is not None:
                score += max(-20.0, min(20.0, month * 2.0))
            if week is not None:
                score += max(-8.0, min(8.0, week))
            notes: list[str] = []
            if month is not None and month > 1.5:
                notes.append("Positive 1m total-return proxy")
            if month is not None and month < -1.5:
                notes.append("Negative 1m — duration/credit pressure")
            sleeves.append(
                BondSleeve(
                    symbol=sym,
                    label=meta["label"],
                    bucket=meta["bucket"],
                    duration=meta["duration"],
                    last=round(closes[-1], 4),
                    day_chg_pct=day,
                    week_chg_pct=week,
                    month_chg_pct=month,
                    score=round(score * self.pipeline_symbol_confidence_factor(sym), 2),
                    notes=notes,
                )
            )

        def mret(sym: str) -> float | None:
            c = closes_map.get(sym)
            return self._pct(c, 21) if c else None

        tlt_m, shy_m, ief_m = mret("TLT"), mret("SHY"), mret("IEF")
        hyg_m, lqd_m, tip_m = mret("HYG"), mret("LQD"), mret("TIP")
        spy_closes = self.fetch_yahoo_closes("SPY", range_="6mo", interval="1d")
        spy_m = self._pct(spy_closes, 21) if spy_closes else None

        # Curve & credit diagnostics
        curve_spread = None
        if tlt_m is not None and shy_m is not None:
            curve_spread = round(tlt_m - shy_m, 3)
        credit_hy_ig = None
        if hyg_m is not None and lqd_m is not None:
            credit_hy_ig = round(hyg_m - lqd_m, 3)
        real_vs_nom = None
        if tip_m is not None and ief_m is not None:
            real_vs_nom = round(tip_m - ief_m, 3)

        if curve_spread is not None and curve_spread > 1.0:
            curve_regime = "long_end_rally"
        elif curve_spread is not None and curve_spread < -1.0:
            curve_regime = "long_end_selloff"
        else:
            curve_regime = "curve_neutral"

        if credit_hy_ig is not None and credit_hy_ig > 0.5:
            credit_regime = "credit_risk_on"
        elif credit_hy_ig is not None and credit_hy_ig < -0.5:
            credit_regime = "credit_stress"
        else:
            credit_regime = "credit_neutral"

        # Overall bond signal: duration leadership + flight-to-quality
        duration_score = 0.0
        if tlt_m is not None:
            duration_score += tlt_m
        if shy_m is not None:
            duration_score += shy_m * 0.3
        if hyg_m is not None and spy_m is not None and hyg_m < spy_m - 2:
            # HY lagging equities hard → caution
            duration_score -= 1.0

        if curve_regime == "long_end_rally" and credit_regime != "credit_stress":
            direction = "BULLISH"
            regime = "bonds_constructive"
        elif curve_regime == "long_end_selloff" or credit_regime == "credit_stress":
            direction = "BEARISH"
            regime = "bonds_pressured"
        else:
            direction = "NEUTRAL"
            regime = "bonds_mixed"

        sleeves.sort(key=lambda s: s.score, reverse=True)
        leaders = [s.symbol for s in sleeves[:5]]
        laggards = [s.symbol for s in sleeves[-4:]]

        recs = [
            f"Bond regime: {regime} | curve={curve_regime} | credit={credit_regime}.",
            f"1m TLT−SHY spread proxy: {curve_spread if curve_spread is not None else 'n/a'} pp.",
            f"1m HYG−LQD credit proxy: {credit_hy_ig if credit_hy_ig is not None else 'n/a'} pp.",
            f"1m TIP−IEF real-yield proxy: {real_vs_nom if real_vs_nom is not None else 'n/a'} pp.",
            f"Relative bond leaders: {', '.join(leaders)}.",
        ]
        if direction == "BULLISH":
            recs.append("Bias: extend duration modestly (IEF/TLT) if policy easing; keep HY size disciplined.")
        elif direction == "BEARISH":
            recs.append("Bias: shorten duration (SHY/SGOV/BIL); treat HYG as equity beta, not ballast.")
        else:
            recs.append("Bias: barbell cash-like + selective IG; avoid oversized long-duration until curve clears.")
        if credit_regime == "credit_stress":
            recs.append("Credit stress: prefer LQD/quality IG over HYG; watch equity correlation.")
        recs = self.append_memory_recommendations(recs)

        conf = 0.5
        if curve_spread is not None:
            conf += min(0.2, abs(curve_spread) / 10.0)
        if credit_hy_ig is not None:
            conf += min(0.15, abs(credit_hy_ig) / 8.0)

        return {
            "status": "ok" if sleeves else "degraded",
            "regime": regime,
            "curve_regime": curve_regime,
            "credit_regime": credit_regime,
            "diagnostics": {
                "tlt_minus_shy_1m_pp": curve_spread,
                "hyg_minus_lqd_1m_pp": credit_hy_ig,
                "tip_minus_ief_1m_pp": real_vs_nom,
                "spy_1m_chg_pct": spy_m,
                "tlt_1m_chg_pct": tlt_m,
                "shy_1m_chg_pct": shy_m,
                "hyg_1m_chg_pct": hyg_m,
                "lqd_1m_chg_pct": lqd_m,
            },
            "sleeves": [asdict(s) for s in sleeves],
            "leaders": leaders,
            "laggards": laggards,
            "playbook": BOND_PLAYBOOK,
            "recommendations": recs,
            "errors": errors[:20],
            "signal": {
                "direction": direction,
                "confidence": round(min(0.88, conf), 3),
                "horizon": self.preferred_horizon() or "1mo",
            },
            "tickers_bullish": leaders[:4],
            "tickers_bearish": laggards[:4],
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        body = self.analyze()
        payload = {
            "agent": "bond-markets",
            "label": "Bond Markets & Fixed-Income Expert",
            "temperature": self.temperature,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Yahoo Finance bond ETF proxies",
            "dashboard": DASHBOARD_URL,
            "domain": "fixed_income",
            **body,
        }
        try:
            from agent_groups import apply_group_conduct_to_report

            payload = apply_group_conduct_to_report(payload, "bond-markets")
        except Exception:
            pass
        out = output or DEFAULT_OUTPUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


def run_bond_markets_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return BondMarketsExpert(pipeline_context=pipeline_context).run(output=output)
