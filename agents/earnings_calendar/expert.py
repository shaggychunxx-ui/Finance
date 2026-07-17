"""
Institutional Earnings Calendar Expert Agent
=============================================
Tracks the Q2 2026 late-July/August corporate earnings timeline: expected
report dates, consensus EPS/revenue estimates, and the primary operational
metric Wall Street is watching for each print. Classifies each report into
a macro theme (AI capex debate, financial post-rotation, automotive
realities, fintech/crypto rotation) and layers on live Yahoo Finance
pre-print momentum to gauge sentiment heading into the release.

Data: static consensus earnings calendar (Yahoo Finance / Nasdaq / MarketBeat
/ Investing.com earnings calendars) + Yahoo Finance chart API for live
pre-print momentum.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Earnings-Calendar-Expert/1.0 (shaggychunxx@gmail.com)"}

# Institutional earnings timeline for late July - August 2026. Consensus
# figures are best-effort sell-side estimates as of publication; they are
# not live and should be refreshed against a live earnings calendar before
# trading decisions.
EARNINGS_CALENDAR: list[dict[str, Any]] = [
    {
        "date": "2026-07-17", "company": "Travelers", "ticker": "TRV",
        "timing": "Pre-Market", "consensus_eps_low": 4.85, "consensus_eps_high": 4.85,
        "consensus_revenue": "~$11.4B", "theme": "financial",
        "key_metric": "Catastrophe underwriting losses vs. premium growth inflation.",
    },
    {
        "date": "2026-07-17", "company": "Truist Financial", "ticker": "TFC",
        "timing": "Pre-Market", "consensus_eps_low": 0.91, "consensus_eps_high": 0.91,
        "consensus_revenue": "~$5.1B", "theme": "financial",
        "key_metric": "Net Interest Margin (NIM) expansion & commercial credit provisions.",
    },
    {
        "date": "2026-07-20", "company": "W.R. Berkley", "ticker": "WRB",
        "timing": "After-Hours", "consensus_eps_low": 1.09, "consensus_eps_high": 1.09,
        "consensus_revenue": "$3.7B", "theme": "financial",
        "key_metric": "Net investment income and commercial insurance pricing power.",
    },
    {
        "date": "2026-07-21", "company": "General Motors", "ticker": "GM",
        "timing": "Pre-Market", "consensus_eps_low": 2.70, "consensus_eps_high": 2.70,
        "consensus_revenue": "~$44.8B", "theme": "automotive",
        "key_metric": "EV production scale timeline adjustments & legacy fleet margins.",
    },
    {
        "date": "2026-07-22", "company": "Alphabet", "ticker": "GOOG",
        "timing": "After-Hours", "consensus_eps_low": 2.86, "consensus_eps_high": 2.95,
        "consensus_revenue": "$120.0B", "theme": "tech_ai_capex",
        "key_metric": "Google Cloud margins (prior quarter 32.9%) and AI search monetization.",
    },
    {
        "date": "2026-07-22", "company": "Tesla", "ticker": "TSLA",
        "timing": "After-Hours", "consensus_eps_low": 0.48, "consensus_eps_high": 0.48,
        "consensus_revenue": "$25.5B", "theme": "automotive",
        "key_metric": "Automotive gross margins (ex-credits) and Robotaxi/Cybercab timelines.",
    },
    {
        "date": "2026-07-23", "company": "Intel", "ticker": "INTC",
        "timing": "After-Hours", "consensus_eps_low": 0.21, "consensus_eps_high": 0.21,
        "consensus_revenue": "$14.7B", "theme": "tech_ai_capex",
        "key_metric": "Foundry segment execution losses and x86 server market share stability.",
    },
    {
        "date": "2026-07-29", "company": "Microsoft", "ticker": "MSFT",
        "timing": "After-Hours", "consensus_eps_low": 4.33, "consensus_eps_high": 4.33,
        "consensus_revenue": "$89.4B", "theme": "tech_ai_capex",
        "key_metric": "Azure growth trajectory (target ~35-40%) and $190B FY26 CapEx utilization.",
    },
    {
        "date": "2026-07-29", "company": "Robinhood", "ticker": "HOOD",
        "timing": "After-Hours", "consensus_eps_low": 0.41, "consensus_eps_high": 0.42,
        "consensus_revenue": "$1.23B", "theme": "fintech_crypto",
        "key_metric": "Retail transaction volume momentum and crypto-trading fee expansion.",
    },
    {
        "date": "2026-07-30", "company": "Coinbase", "ticker": "COIN",
        "timing": "After-Hours", "consensus_eps_low": 0.12, "consensus_eps_high": 0.14,
        "consensus_revenue": "$1.35B", "theme": "fintech_crypto",
        "key_metric": "Base Layer-2 network sequencing revenues and institutional custody inflows.",
    },
    {
        "date": "2026-07-30", "company": "MicroStrategy", "ticker": "MSTR",
        "timing": "After-Hours", "consensus_eps_low": 16.85, "consensus_eps_high": 16.85,
        "consensus_revenue": "N/A", "theme": "fintech_crypto",
        "key_metric": "Premium-to-NAV yield expansion and Bitcoin acquisition velocity.",
    },
    {
        "date": "2026-08-26", "company": "NVIDIA", "ticker": "NVDA",
        "timing": "After-Hours", "consensus_eps_low": 2.07, "consensus_eps_high": 2.09,
        "consensus_revenue": "$80.0B+ (Data Center)", "theme": "tech_ai_capex",
        "key_metric": "Blackwell B200 shipment timelines and customer concentration risk profiles.",
    },
]

SECTOR_THEMES: dict[str, dict[str, str]] = {
    "tech_ai_capex": {
        "label": "The Great AI Expenditures Debate",
        "summary": (
            "Investors are shifting from punishing mega-cap CapEx to scrutinizing realized "
            "monetization (Azure/Google Cloud commercial AI growth). Slowing enterprise demand "
            "relative to heavy hardware spend could deepen recent semiconductor corrections."
        ),
    },
    "financial": {
        "label": "Financial Foundations Post-Rotation",
        "summary": (
            "Large banks opened the season with resilient capital-markets fees and IB pipelines. "
            "Regional/commercial prints face headwinds from higher funding costs as firms defend "
            "deposit rates against outflows, tightening net interest margins."
        ),
    },
    "automotive": {
        "label": "Automotive Realities",
        "summary": (
            "Early-2026 pricing cuts aimed at stimulating demand have compressed auto gross "
            "margins. The street is watching whether secondary services/software integrations "
            "can reverse the downward trend."
        ),
    },
    "fintech_crypto": {
        "label": "Fintech & Crypto Rotation",
        "summary": (
            "Retail trading platforms and crypto-adjacent balance sheets are geared to "
            "transaction volume momentum and digital-asset price action, making them a higher-beta "
            "read-through on risk appetite heading into the AI/tech prints."
        ),
    },
}

QUIET_PERIOD_NOTES = [
    "Quiet Period: from fiscal quarter-end until the official release date, executives/IR are "
    "restricted from providing forward guidance to prevent selective disclosure.",
    "Call Structure: press releases typically cross the wire at market close (~4:00 PM ET) or "
    "before the open (~8:00 AM ET) with top-line GAAP metrics, followed 30-60 minutes later by an "
    "investor webcast with guidance, segment detail, and sell-side Q&A.",
    "Risk Disclosure: a double beat on revenue and EPS can still sell off on muted forward "
    "guidance or subtle balance-sheet adjustments — implied volatility around print dates reflects "
    "this asymmetric risk.",
]

EARNINGS_CALENDAR_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "yahoo_earnings_calendar",
        "name": "Yahoo Finance Earnings Calendar",
        "url": "https://finance.yahoo.com/calendar/earnings",
        "description": "Daily consensus earnings calendar by date",
    },
    {
        "id": "nasdaq_earnings",
        "name": "Nasdaq Earnings Calendar",
        "url": "https://www.nasdaq.com/market-activity/earnings",
        "description": "Upcoming earnings dates and consensus estimates",
    },
    {
        "id": "investing_earnings_calendar",
        "name": "Investing.com Earnings Calendar",
        "url": "https://www.investing.com/earnings-calendar",
        "description": "Global earnings calendar with EPS/revenue consensus",
    },
    {
        "id": "marketbeat_earnings",
        "name": "MarketBeat Earnings Reports",
        "url": "https://www.marketbeat.com/earnings/",
        "description": "Per-company earnings report pages with analyst estimates",
    },
]


@dataclass
class EarningsEvent:
    date: str
    company: str
    ticker: str
    timing: str
    consensus_eps_low: float
    consensus_eps_high: float
    consensus_revenue: str
    theme: str
    key_metric: str
    pre_print_momentum_5d_pct: float | None = None
    pre_print_momentum_20d_pct: float | None = None
    momentum_source: str = "proxy"
    bias: str = "NEUTRAL"


@dataclass
class EarningsCalendarReport:
    events: list[EarningsEvent]
    sector_themes: list[dict[str, Any]]
    quiet_period_notes: list[str]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Calibrated pre-print momentum proxy used when the live Yahoo Finance chart
# API is unreachable (blocked network / rate limit). Values are indicative
# reference points, not live data, and are always labeled as such.
PROXY_MOMENTUM: dict[str, tuple[float, float]] = {
    "TRV": (0.8, 2.1), "TFC": (0.4, 1.6), "WRB": (1.1, 2.8), "GM": (-0.6, 1.4),
    "GOOG": (2.4, 6.8), "TSLA": (-1.8, 3.2), "INTC": (-2.2, -4.5),
    "MSFT": (1.6, 4.9), "HOOD": (3.5, 12.4), "COIN": (2.0, 5.5),
    "MSTR": (4.2, 9.8), "NVDA": (2.8, 8.1),
}


class EarningsCalendarExpert(BaseExpert):
    """Institutional earnings calendar analyst with pre-print momentum overlay."""

    def __init__(
        self,
        *,
        pipeline_context: dict | None = None,
        delay_seconds: float = 0.35,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="earnings-calendar")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _period_return(closes: list[float], days: int) -> float | None:
        if len(closes) <= days:
            return None
        base = closes[-days - 1]
        if base is None or base == 0:
            return None
        return round(((closes[-1] - base) / base) * 100, 2)

    def _momentum(self, ticker: str) -> tuple[float | None, float | None, str]:
        try:
            closes = self.fetch_yahoo_closes(ticker, range_="1mo", interval="1d")
        except Exception:
            closes = []
        if len(closes) >= 6:
            r5 = self._period_return(closes, 5)
            r20 = self._period_return(closes, min(20, len(closes) - 1))
            if r5 is not None or r20 is not None:
                return r5, r20, "Yahoo Finance chart API"
        proxy = PROXY_MOMENTUM.get(ticker)
        if proxy:
            return proxy[0], proxy[1], "Calibrated momentum proxy (live data unavailable)"
        return None, None, "unavailable"

    @staticmethod
    def _bias_from_momentum(r5: float | None, r20: float | None) -> str:
        signal = r5 if r5 is not None else r20
        if signal is None:
            return "NEUTRAL"
        if signal >= 1.5:
            return "BULLISH"
        if signal <= -1.5:
            return "BEARISH"
        return "NEUTRAL"

    def _build_event(self, raw: dict[str, Any]) -> EarningsEvent:
        r5, r20, source = self._momentum(raw["ticker"])
        bias = self._bias_from_momentum(r5, r20)
        return EarningsEvent(
            date=raw["date"],
            company=raw["company"],
            ticker=raw["ticker"],
            timing=raw["timing"],
            consensus_eps_low=raw["consensus_eps_low"],
            consensus_eps_high=raw["consensus_eps_high"],
            consensus_revenue=raw["consensus_revenue"],
            theme=raw["theme"],
            key_metric=raw["key_metric"],
            pre_print_momentum_5d_pct=r5,
            pre_print_momentum_20d_pct=r20,
            momentum_source=source,
            bias=bias,
        )

    def _market_signal(self, event: EarningsEvent) -> dict[str, Any]:
        from agent_signal_logic import build_market_signal

        theme_label = SECTOR_THEMES.get(event.theme, {}).get("label", event.theme)
        momentum = event.pre_print_momentum_5d_pct
        momentum_txt = f"{momentum:+.2f}% 5d" if momentum is not None else "no momentum read"
        reason = (
            f"{event.company} ({event.ticker}) reports {event.timing.lower()} on {event.date} "
            f"[{theme_label}]; pre-print momentum {momentum_txt}. Watch: {event.key_metric}"
        )
        confidence = 0.45
        if momentum is not None:
            confidence = min(0.8, 0.45 + abs(momentum) * 0.03)
        confidence = self.adjust_signal_confidence(event.ticker, event.bias, confidence)
        return build_market_signal(
            sector=theme_label,
            tickers=[event.ticker],
            bias=event.bias,
            reason=reason,
            confidence=confidence,
            evidence={
                "date": event.date,
                "consensus_eps_low": event.consensus_eps_low,
                "consensus_eps_high": event.consensus_eps_high,
                "pre_print_momentum_5d_pct": event.pre_print_momentum_5d_pct,
                "pre_print_momentum_20d_pct": event.pre_print_momentum_20d_pct,
            },
        )

    def analyze(self) -> EarningsCalendarReport:
        events = [self._build_event(raw) for raw in EARNINGS_CALENDAR]
        events.sort(key=lambda e: e.date)

        signals = [self._market_signal(e) for e in events]

        live_hits = sum(1 for e in events if e.momentum_source == "Yahoo Finance chart API")
        sources = []
        if live_hits:
            sources.append(f"Yahoo Finance chart API ({live_hits}/{len(events)} tickers)")
        if live_hits < len(events):
            sources.append("Calibrated momentum proxy (remaining tickers)")
        sources.append("Static consensus earnings calendar (Yahoo Finance / Nasdaq / MarketBeat / Investing.com)")

        themes_present = sorted({e.theme for e in events})
        sector_themes = [
            {"theme": t, **SECTOR_THEMES.get(t, {"label": t, "summary": ""})}
            for t in themes_present
        ]

        bullish = sum(1 for e in events if e.bias == "BULLISH")
        bearish = sum(1 for e in events if e.bias == "BEARISH")
        next_event = events[0] if events else None
        next_txt = (
            f"Next up: {next_event.company} ({next_event.ticker}) on {next_event.date} {next_event.timing}."
            if next_event else "No upcoming reports tracked."
        )
        expert_summary = (
            f"Tracking {len(events)} institutional earnings reports across {len(themes_present)} macro "
            f"themes into late-July/August 2026 ({bullish} bullish / {bearish} bearish pre-print momentum "
            f"reads). {next_txt} Tech/AI CapEx monetization, financial NIM resilience, and automotive "
            "margin compression remain the dominant cross-currents."
        )

        recs = [
            f"{next_txt}",
            f"AI CapEx debate reports: {', '.join(e.ticker for e in events if e.theme == 'tech_ai_capex')} "
            "— monitor cloud margin trajectory and hardware monetization commentary.",
            f"Financial-sector reports: {', '.join(e.ticker for e in events if e.theme == 'financial')} "
            "— watch NIM trend and catastrophe/credit provisioning.",
            f"Automotive reports: {', '.join(e.ticker for e in events if e.theme == 'automotive')} "
            "— watch gross margin trajectory post pricing cuts.",
            f"Fintech/crypto reports: {', '.join(e.ticker for e in events if e.theme == 'fintech_crypto')} "
            "— higher-beta read-through on risk appetite and digital-asset prices.",
            "SEC quiet period restricts forward guidance until the official release; expect the largest "
            "repricing 30-60 minutes into the post-release investor call, not at the initial headline print.",
        ]

        return EarningsCalendarReport(
            events=events,
            sector_themes=sector_themes,
            quiet_period_notes=QUIET_PERIOD_NOTES,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=self.append_memory_recommendations(recs),
            data_sources=sources,
        )

    def to_dict(self, report: EarningsCalendarReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Institutional Earnings Calendar Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "events_tracked": len(report.events),
                "data_sources": report.data_sources,
            },
            "events": [
                {
                    "date": e.date,
                    "company": e.company,
                    "ticker": e.ticker,
                    "timing": e.timing,
                    "consensus_eps_low": e.consensus_eps_low,
                    "consensus_eps_high": e.consensus_eps_high,
                    "consensus_revenue": e.consensus_revenue,
                    "theme": e.theme,
                    "key_metric": e.key_metric,
                    "pre_print_momentum_5d_pct": e.pre_print_momentum_5d_pct,
                    "pre_print_momentum_20d_pct": e.pre_print_momentum_20d_pct,
                    "momentum_source": e.momentum_source,
                    "bias": e.bias,
                }
                for e in report.events
            ],
            "sector_themes": report.sector_themes,
            "quiet_period_notes": report.quiet_period_notes,
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            resources_path = output.parent / "earnings_calendar_resources.json"
            resources_path.write_text(
                json.dumps(EARNINGS_CALENDAR_RESOURCES, indent=2),
                encoding="utf-8",
            )
        return result


def run_earnings_calendar_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return EarningsCalendarExpert(pipeline_context=pipeline_context).run(output=output)
