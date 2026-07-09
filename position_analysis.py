"""Build detailed agent analysis explanations for trade positions."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from agents.platform_catalog import active_agent_sources

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"

HORIZON_LABELS = {
    "24h": "24 hours",
    "1wk": "1 week",
    "1mo": "1 month",
    "1yr": "1 year",
}

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Finance/1.0)"}
_profile_cache: dict[str, tuple[float, dict[str, Any]]] = {}
PROFILE_CACHE_TTL = 3600.0

ETF_BLURBS: dict[str, str] = {
    "UNG": "Exchange-traded fund tracking U.S. natural gas futures; moves with weather, storage, and energy demand.",
    "USO": "ETF tracking crude oil futures; sensitive to global supply, OPEC policy, and macro risk sentiment.",
    "SPY": "ETF tracking the S&P 500 — broad U.S. large-cap equity benchmark.",
    "QQQ": "ETF tracking the Nasdaq-100 — tilted toward large-cap technology and growth stocks.",
    "IWM": "ETF tracking the Russell 2000 — U.S. small-cap equity exposure.",
    "XLE": "Sector ETF for U.S. energy stocks including oil, gas, and equipment producers.",
    "XLU": "Sector ETF for U.S. regulated utilities and power producers.",
    "GLD": "ETF backed by physical gold — common risk-off and inflation-hedge vehicle.",
    "TLT": "ETF of long-duration U.S. Treasury bonds — benefits when yields fall and risk appetite fades.",
}


@dataclass
class AgentReasonBlock:
    agent_id: str
    agent_name: str
    category: str
    weight: float | None
    accuracy: str
    reasons: list[str] = field(default_factory=list)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _norm(symbol: str) -> str:
    return (symbol or "").strip().upper().replace(".", "-")


def _section(title: str, lines: list[str]) -> list[str]:
    if not lines:
        return []
    out = [title, "-" * len(title)]
    out.extend(lines)
    out.append("")
    return out


def _title_case_name(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text.isupper():
        return text.title()
    return text


def _enhanced_quote(output_dir: Path, symbol: str) -> dict[str, Any] | None:
    data = _load_json(output_dir / "etrade_enhanced_quotes.json") or {}
    row = (data.get("quotes") or {}).get(_norm(symbol))
    return row if isinstance(row, dict) else None


def _chart_meta(symbol: str) -> dict[str, Any]:
    sym = _norm(symbol)
    try:
        resp = requests.get(
            CHART_API.format(symbol=sym),
            params={"interval": "1d", "range": "5d"},
            headers=HEADERS,
            timeout=18,
        )
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if result:
            return result[0].get("meta") or {}
    except Exception:
        pass
    return {}


def _infer_sector(output_dir: Path, symbol: str) -> tuple[str, str]:
    sym = _norm(symbol)
    for src in active_agent_sources():
        data = _load_json(output_dir / src["file"])
        if not data:
            continue
        for sig in data.get("market_signals", []) or []:
            tickers = {_norm(t) for t in sig.get("tickers", [])}
            if sym in tickers:
                sector = str(sig.get("sector") or sig.get("category") or "").strip()
                if sector:
                    return sector, ""
    data = _load_json(output_dir / "financial_data.json") or {}
    for row in data.get("sectors", []) or []:
        tickers = {_norm(t) for t in row.get("tickers", []) or row.get("constituents", [])}
        if sym in tickers:
            return str(row.get("name") or row.get("sector") or ""), ""
    return "", ""


def _synthesize_description(
    symbol: str,
    *,
    output_dir: Path,
    instrument_type: str = "",
    exchange: str = "",
) -> str:
    sym = _norm(symbol)
    if sym in ETF_BLURBS:
        return ETF_BLURBS[sym]

    finance = _finance_opportunity(output_dir, sym)
    if finance and finance.get("rationale"):
        return str(finance["rationale"])[:420]

    portfolio = _load_json(output_dir / "portfolio.json") or {}
    for row in portfolio.get("holdings", []) or []:
        if _norm(row.get("symbol", "")) == sym and row.get("rationale"):
            text = str(row["rationale"])
            if len(text) > 40:
                return text[:420]

    for src in active_agent_sources():
        data = _load_json(output_dir / src["file"])
        if not data:
            continue
        for pick in data.get("top_picks", []) or []:
            if _norm(pick.get("symbol", "")) == sym and pick.get("rationale"):
                return str(pick["rationale"])[:420]

    kind = (instrument_type or "security").replace("_", " ").lower()
    if exchange:
        return f"{exchange}-listed {kind}. Selected by agents based on live signals and portfolio fit."
    return f"Publicly traded {kind}. Selected by agents based on live signals and portfolio fit."


def get_company_profile(symbol: str, *, output_dir: Path | None = None) -> dict[str, Any]:
    """Return company name, sector, and a short business description."""
    output_dir = output_dir or OUTPUT
    sym = _norm(symbol)
    profile: dict[str, Any] = {"symbol": sym, "name": sym, "sector": "", "industry": "", "description": ""}

    now = time.time()
    cached = _profile_cache.get(sym)
    if cached and now - cached[0] < PROFILE_CACHE_TTL:
        profile.update(cached[1])
        quote = _enhanced_quote(output_dir, sym)
        if quote:
            if quote.get("last_trade") is not None:
                profile["price"] = float(quote["last_trade"])
            if quote.get("change_pct") is not None:
                profile["change_pct"] = float(quote["change_pct"])
            if quote.get("market_cap") is not None:
                profile["market_cap"] = float(quote["market_cap"])
            if quote.get("pe") is not None:
                profile["pe"] = float(quote["pe"])
        return profile

    quote = _enhanced_quote(output_dir, sym)
    if quote:
        profile["name"] = _title_case_name(str(quote.get("company_name") or sym))
        if quote.get("last_trade") is not None:
            profile["price"] = float(quote["last_trade"])
        if quote.get("change_pct") is not None:
            profile["change_pct"] = float(quote["change_pct"])
        if quote.get("market_cap") is not None:
            profile["market_cap"] = float(quote["market_cap"])
        if quote.get("pe") is not None:
            profile["pe"] = float(quote["pe"])

    meta = _chart_meta(sym)
    if meta.get("longName") or meta.get("shortName"):
        profile["name"] = _title_case_name(str(meta.get("longName") or meta.get("shortName") or profile["name"]))
    profile["exchange"] = str(meta.get("fullExchangeName") or meta.get("exchangeName") or "")
    profile["instrument_type"] = str(meta.get("instrumentType") or "")

    sector, industry = _infer_sector(output_dir, sym)
    profile["sector"] = sector or profile.get("sector", "")
    profile["industry"] = industry or profile.get("industry", "")
    profile["description"] = _synthesize_description(
        sym,
        output_dir=output_dir,
        instrument_type=profile.get("instrument_type", ""),
        exchange=profile.get("exchange", ""),
    )

    _profile_cache[sym] = (
        now,
        {
            "symbol": sym,
            "name": profile.get("name"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "description": profile.get("description"),
            "exchange": profile.get("exchange"),
            "instrument_type": profile.get("instrument_type"),
        },
    )
    return profile


def _prediction_rows(output_dir: Path, symbol: str) -> list[dict[str, Any]]:
    data = _load_json(output_dir / "market_predictions.json") or {}
    sym = _norm(symbol)
    rows: list[dict[str, Any]] = []
    for horizon, label in HORIZON_LABELS.items():
        for row in (data.get("predictions") or {}).get(horizon, []) or []:
            if _norm(row.get("symbol", "")) == sym:
                rows.append({**row, "horizon": horizon, "horizon_label": label})
                break
    return rows


def _finance_opportunity(output_dir: Path, symbol: str) -> dict[str, Any] | None:
    data = _load_json(output_dir / "finance.json") or {}
    sym = _norm(symbol)
    for opp in data.get("trading_opportunities", []) or []:
        if _norm(opp.get("symbol", "")) == sym:
            return opp
    return None


def _agent_category(agent_id: str) -> str:
    try:
        from agents.platform_catalog import CATEGORY_BY_ID

        return CATEGORY_BY_ID.get(agent_id, "General")
    except Exception:
        return "General"


def _agent_weight_label(agent_id: str, symbol: str) -> tuple[float | None, str]:
    try:
        from agent_fusion import fusion_weight
        from prediction_accuracy import agent_accuracy_label

        weight = fusion_weight(agent_id, symbol=symbol, horizon="24h")
        return weight, agent_accuracy_label(agent_id)
    except Exception:
        return None, "—"


def _collect_agent_reasoning(
    output_dir: Path,
    symbol: str,
    *,
    holding_sources: set[str] | None = None,
) -> list[AgentReasonBlock]:
    sym = _norm(symbol)
    blocks: list[AgentReasonBlock] = []
    holding_sources = holding_sources or set()

    for src in active_agent_sources():
        data = _load_json(output_dir / src["file"])
        if not data:
            continue
        agent_id = src["id"]
        agent_name = src.get("label") or agent_id
        reasons: list[str] = []

        for sig in data.get("market_signals", []) or []:
            tickers = {_norm(t) for t in sig.get("tickers", [])}
            if sym not in tickers:
                continue
            bias = str(sig.get("bias", "NEUTRAL")).upper()
            sector = sig.get("sector") or sig.get("category") or ""
            reason = sig.get("reason") or sig.get("summary") or ""
            strength = sig.get("strength")
            line = f"Market signal — {bias}"
            if sector:
                line += f" ({sector})"
            if reason:
                line += f": {reason}"
            if strength is not None:
                line += f" [strength {float(strength):.2f}]"
            reasons.append(line)

        for opp in data.get("trading_opportunities", []) or []:
            if _norm(opp.get("symbol", "")) != sym:
                continue
            score = float(opp.get("opportunity_score", 0))
            strategy = opp.get("strategy") or "Opportunity"
            rationale = opp.get("rationale") or ""
            reasons.append(f"Trading opportunity — {strategy} (score {score:.2f})")
            if rationale:
                reasons.append(f"  Rationale: {rationale}")
            if opp.get("day_chg_pct") is not None or opp.get("week_chg_pct") is not None:
                day = opp.get("day_chg_pct")
                week = opp.get("week_chg_pct")
                parts = []
                if day is not None:
                    parts.append(f"day {float(day):+.2f}%")
                if week is not None:
                    parts.append(f"week {float(week):+.2f}%")
                reasons.append(f"  Price action: {', '.join(parts)}")

        for pick in data.get("top_picks", []) or []:
            if _norm(pick.get("symbol", "")) != sym:
                continue
            conf = float(pick.get("confidence", 0.55))
            score = pick.get("score")
            rationale = pick.get("rationale") or "Top quantitative pick"
            line = f"Top pick (confidence {conf:.0%}"
            if score is not None:
                line += f", score {float(score):.2f}"
            line += f"): {rationale}"
            reasons.append(line)

        for factor in data.get("factor_leaders", []) or []:
            if _norm(factor.get("symbol", "")) != sym:
                continue
            reasons.append(
                f"Factor leader — {factor.get('factor', 'factor')} "
                f"(score {float(factor.get('score', 0)):.2f})"
            )

        for row in data.get("tickers", []) or []:
            if _norm(row.get("symbol", "")) != sym:
                continue
            mom = row.get("momentum_score")
            ret = row.get("return_20d_pct")
            vol = row.get("volatility_pct")
            parts = [f"Momentum score {mom}" if mom is not None else ""]
            if ret is not None:
                parts.append(f"20-day return {float(ret):+.1f}%")
            if vol is not None:
                parts.append(f"volatility {float(vol):.1f}%")
            reasons.append("Statistical profile — " + ", ".join(p for p in parts if p))

        for row in data.get("retailers", []) or data.get("retail_leaders", []) or []:
            if _norm(row.get("symbol", "")) != sym:
                continue
            name = row.get("name") or row.get("category") or "Retail leader"
            metric = row.get("sales_growth_pct") or row.get("score")
            if metric is not None:
                reasons.append(f"Retail analytics — {name} (metric {float(metric):.2f})")
            else:
                reasons.append(f"Retail analytics — {name}")

        for row in data.get("movers", []) or data.get("top_movers", []) or []:
            if _norm(row.get("symbol", "")) != sym:
                continue
            chg = row.get("change_pct") or row.get("return_pct")
            label = row.get("label") or row.get("category") or "Mover"
            if chg is not None:
                reasons.append(f"Market mover — {label}: {float(chg):+.2f}%")
            else:
                reasons.append(f"Market mover — {label}")

        if agent_id == "order-execution":
            for row in data.get("execution_notes", []) or data.get("symbol_notes", []) or []:
                if _norm(row.get("symbol", "")) != sym:
                    continue
                note = row.get("note") or row.get("recommendation") or ""
                order_type = row.get("order_type")
                if order_type:
                    reasons.append(f"Execution — prefer {order_type}: {note}".strip(": "))
                elif note:
                    reasons.append(f"Execution — {note}")

        if agent_id == "geopolitics":
            for event in data.get("events", []) or data.get("risk_events", []) or []:
                tickers = {_norm(t) for t in event.get("tickers", []) or event.get("affected_tickers", [])}
                if sym not in tickers:
                    continue
                title = event.get("title") or event.get("event") or "Geopolitical event"
                impact = event.get("impact") or event.get("risk_level") or ""
                detail = event.get("summary") or event.get("analysis") or ""
                line = f"Geopolitical risk — {title}"
                if impact:
                    line += f" ({impact})"
                reasons.append(line)
                if detail:
                    reasons.append(f"  {detail[:220]}")

        if agent_id == "patents":
            for row in data.get("patent_signals", []) or data.get("innovation_signals", []) or []:
                tickers = {_norm(t) for t in row.get("tickers", [])}
                if sym not in tickers and _norm(row.get("symbol", "")) != sym:
                    continue
                topic = row.get("topic") or row.get("category") or "Innovation signal"
                detail = row.get("summary") or row.get("reason") or ""
                reasons.append(f"Patent / innovation — {topic}")
                if detail:
                    reasons.append(f"  {detail[:220]}")

        if not reasons and agent_id in holding_sources:
            reasons.append("Included in fused portfolio score (supporting contributor).")

        if reasons:
            weight, accuracy = _agent_weight_label(agent_id, sym)
            blocks.append(
                AgentReasonBlock(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    category=_agent_category(agent_id),
                    weight=weight,
                    accuracy=accuracy,
                    reasons=reasons[:6],
                )
            )

    preds = _prediction_rows(output_dir, sym)
    if preds:
        mp_reasons: list[str] = []
        for row in preds[:2]:
            sources = ", ".join(row.get("sources") or [])
            mp_reasons.append(
                f"{row['horizon_label']}: {str(row.get('predicted_direction', 'flat')).upper()} "
                f"{float(row.get('predicted_return_pct', 0)):+.2f}% "
                f"(confidence {float(row.get('confidence', 0)):.0%}, rank #{row.get('rank', '—')})"
            )
            if row.get("rationale"):
                mp_reasons.append(f"  Fusion rationale: {row['rationale']}")
            if sources:
                mp_reasons.append(f"  Contributing agents: {sources}")
        weight, accuracy = _agent_weight_label("market-predictor", sym)
        blocks.insert(
            0,
            AgentReasonBlock(
                agent_id="market-predictor",
                agent_name="Market Predictor",
                category="Markets & Finance",
                weight=weight,
                accuracy=accuracy,
                reasons=mp_reasons,
            ),
        )

    quote = _enhanced_quote(output_dir, sym)
    if quote:
        chg = quote.get("change_pct")
        last = quote.get("last_trade")
        etrade_lines = []
        if last is not None:
            etrade_lines.append(f"Live E*TRADE quote: ${float(last):.2f}")
        if chg is not None:
            etrade_lines.append(f"Session change: {float(chg):+.2f}%")
        if quote.get("volume") is not None:
            etrade_lines.append(f"Volume: {int(quote['volume']):,}")
        if etrade_lines:
            blocks.append(
                AgentReasonBlock(
                    agent_id="etrade",
                    agent_name="E*TRADE Live Data",
                    category="Market Data",
                    weight=None,
                    accuracy="—",
                    reasons=etrade_lines,
                )
            )

    try:
        from analysis_history import get_persistent_bullish_tickers

        for row in get_persistent_bullish_tickers(top_n=40):
            if _norm(row.get("symbol", "")) != sym:
                continue
            blocks.append(
                AgentReasonBlock(
                    agent_id="history",
                    agent_name="Analysis History",
                    category="Historical Signals",
                    weight=None,
                    accuracy="—",
                    reasons=[
                        f"Persistent bullish across {row.get('bullish_hits', 0)} cycles "
                        f"(avg score {float(row.get('avg_score', 0)):.2f}, "
                        f"composite {float(row.get('composite', 0)):.2f})"
                    ],
                )
            )
            break
    except Exception:
        pass

    blocks.sort(
        key=lambda block: (
            0 if block.agent_id == "market-predictor" else 1,
            -(block.weight or 0),
            block.agent_name,
        ),
    )
    return blocks


def _format_agent_reasoning(blocks: list[AgentReasonBlock]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        header = f"▸ {block.agent_name} ({block.category})"
        meta: list[str] = []
        if block.weight is not None:
            meta.append(f"fusion weight {block.weight:.2f}×")
        if block.accuracy and block.accuracy != "—":
            meta.append(f"accuracy {block.accuracy}")
        if meta:
            header += f" — {', '.join(meta)}"
        lines.append(header)
        lines.extend(f"  {reason}" for reason in block.reasons)
        lines.append("")
    return lines


def build_position_analysis(
    symbol: str,
    *,
    output_dir: Path | None = None,
    holding: dict[str, Any] | None = None,
    current_position: dict[str, Any] | None = None,
    order: Any | None = None,
    day_position: dict[str, Any] | None = None,
) -> str:
    """Return a readable analysis brief for *symbol*."""
    output_dir = output_dir or OUTPUT
    sym = _norm(symbol)
    lines: list[str] = []

    profile = get_company_profile(sym, output_dir=output_dir)
    company_lines = [profile.get("name") or sym]
    if profile.get("sector") or profile.get("industry"):
        company_lines.append(
            " · ".join(
                part
                for part in (
                    str(profile.get("sector") or "").strip(),
                    str(profile.get("industry") or "").strip(),
                )
                if part
            )
        )
    if profile.get("price") is not None:
        price_line = f"Last price: ${float(profile['price']):.2f}"
        if profile.get("change_pct") is not None:
            price_line += f" ({float(profile['change_pct']):+.2f}% today)"
        company_lines.append(price_line)
    if profile.get("market_cap") is not None:
        company_lines.append(f"Market cap: ${float(profile['market_cap']):,.0f}")
    if profile.get("pe") is not None:
        company_lines.append(f"P/E: {float(profile['pe']):.1f}")
    if profile.get("description"):
        company_lines.append(profile["description"])
    lines.extend(_section("Company", company_lines))

    if holding is None:
        portfolio = _load_json(output_dir / "portfolio.json") or {}
        for row in portfolio.get("holdings", []) or []:
            if _norm(row.get("symbol", "")) == sym:
                holding = row
                break

    overview: list[str] = []
    if holding:
        if holding.get("role"):
            overview.append(f"Role: {str(holding['role']).replace('_', ' ')}")
        sources = holding.get("sources") or []
        if sources:
            overview.append(f"Portfolio contributors: {', '.join(sources)}")
        if holding.get("score") is not None:
            overview.append(f"Composite agent score: {float(holding['score']):.2f}")
        if holding.get("confidence") is not None:
            overview.append(f"Confidence: {float(holding['confidence']):.0%}")
        if holding.get("weight_pct") is not None:
            overview.append(f"Target portfolio weight: {float(holding['weight_pct']):.2f}%")
        if holding.get("allocation_usd") is not None:
            overview.append(f"Target allocation: ${float(holding['allocation_usd']):,.2f}")
        if holding.get("projected_return_pct") is not None:
            overview.append(f"Projected return: {float(holding['projected_return_pct']):+.2f}%")
        if holding.get("rationale"):
            overview.append(f"Portfolio summary: {holding['rationale']}")
    elif day_position:
        overview.append("Intraday position — not a long-term portfolio holding.")
    elif current_position:
        overview.append("Held in your account but not in the current agent target portfolio.")
    else:
        overview.append("No active agent portfolio entry — analysis from latest agent reports.")
    lines.extend(_section("Position overview", overview))

    holding_sources = set(holding.get("sources") or []) if holding else set()
    reasoning = _collect_agent_reasoning(output_dir, sym, holding_sources=holding_sources)
    if reasoning:
        lines.extend(_section("Why agents chose this position", _format_agent_reasoning(reasoning)))

    finance = _finance_opportunity(output_dir, sym)
    if finance:
        fin_lines = [
            f"Strategy: {finance.get('strategy', '—')}",
            f"Opportunity score: {float(finance.get('opportunity_score', 0)):.2f}",
        ]
        if finance.get("day_chg_pct") is not None:
            fin_lines.append(f"Day change: {float(finance['day_chg_pct']):+.2f}%")
        if finance.get("week_chg_pct") is not None:
            fin_lines.append(f"Week change: {float(finance['week_chg_pct']):+.2f}%")
        if finance.get("order_type"):
            fin_lines.append(f"Order type: {finance['order_type']}")
        if finance.get("rationale"):
            fin_lines.append(f"Rationale: {finance['rationale']}")
        lines.extend(_section("Finance Agent (dedicated pick)", fin_lines))

    account_lines: list[str] = []
    if current_position:
        qty = current_position.get("quantity", 0)
        mv = float(current_position.get("market_value", 0))
        px = current_position.get("price")
        account_lines.append(f"Your position: {qty} shares, ${mv:,.2f} market value")
        if px is not None:
            account_lines.append(f"Last price: ${float(px):,.2f}")
    if order is not None:
        account_lines.append(
            f"Proposed {order.action} {order.quantity} shares "
            f"({getattr(order, 'price_type', 'MARKET')})"
        )
        if getattr(order, "limit_price", None) is not None:
            account_lines.append(f"Limit price: ${float(order.limit_price):.2f}")
        if order.rationale:
            account_lines.append(f"Trade rationale: {order.rationale}")
        if order.message:
            account_lines.append(f"Status: {order.message}")
    if day_position:
        account_lines.append(
            f"Day trade: {day_position.get('quantity', 0)} shares @ "
            f"${float(day_position.get('entry_price', 0)):.2f}"
        )
        account_lines.append(
            f"Take profit: +{float(day_position.get('take_profit_pct', 0)):.2f}% · "
            f"Stop loss: -{float(day_position.get('stop_loss_pct', 0)):.2f}%"
        )
        if day_position.get("rationale"):
            account_lines.append(f"Entry note: {day_position['rationale']}")
    if holding and holding.get("order_type"):
        account_lines.append(f"Agent order type: {holding['order_type']}")
        if holding.get("limit_price") is not None:
            account_lines.append(f"Agent limit price: ${float(holding['limit_price']):.2f}")
        if holding.get("order_type_reason"):
            account_lines.append(f"Why: {holding['order_type_reason']}")
    if account_lines:
        lines.extend(_section("Position & trade plan", account_lines))

    regime = _load_json(output_dir / "portfolio.json")
    if isinstance(regime, dict) and regime.get("regime"):
        reg = regime["regime"]
        lines.extend(
            _section(
                "Market context",
                [
                    f"{reg.get('label', 'Neutral')} ({reg.get('posture', 'neutral')})",
                    (reg.get("summary") or "")[:400],
                ],
            )
        )

    if len(lines) <= 2:
        lines.append("No detailed agent analysis is available for this symbol yet.")
        lines.append("Run the agent pipeline and rebuild the strategy plan.")

    return "\n".join(lines).strip() + "\n"