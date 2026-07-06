"""Build detailed agent analysis explanations for trade positions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.platform_catalog import active_agent_sources

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"

HORIZON_LABELS = {
    "24h": "24 hours",
    "1wk": "1 week",
    "1mo": "1 month",
    "1yr": "1 year",
}


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


def _agent_mentions(output_dir: Path, symbol: str) -> list[str]:
    sym = _norm(symbol)
    mentions: list[str] = []
    for src in active_agent_sources():
        data = _load_json(output_dir / src["file"])
        if not data:
            continue
        agent_name = src.get("label") or src["id"]
        hits: list[str] = []

        for sig in data.get("market_signals", []) or []:
            tickers = {_norm(t) for t in sig.get("tickers", [])}
            if sym not in tickers:
                continue
            bias = sig.get("bias", "NEUTRAL")
            reason = sig.get("reason") or sig.get("sector") or ""
            hits.append(f"{bias}: {reason}".strip(": "))

        for opp in data.get("trading_opportunities", []) or []:
            if _norm(opp.get("symbol", "")) == sym:
                hits.append(opp.get("rationale") or opp.get("strategy", "Trading opportunity"))

        for pick in data.get("top_picks", []) or []:
            if _norm(pick.get("symbol", "")) == sym:
                hits.append(pick.get("rationale") or "Top data-science pick")

        for row in data.get("tickers", []) or []:
            if _norm(row.get("symbol", "")) == sym:
                mom = row.get("momentum_score")
                ret = row.get("return_20d_pct")
                hits.append(f"Momentum {mom}, 20d {ret:+.1f}%" if ret is not None else f"Momentum {mom}")

        for row in data.get("retailers", []) or data.get("retail_leaders", []) or []:
            if _norm(row.get("symbol", "")) == sym:
                hits.append(row.get("name") or row.get("category") or "Retail leader")

        if hits:
            for note in hits[:3]:
                mentions.append(f"• {agent_name}: {note}")
    return mentions


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

    if holding is None:
        portfolio = _load_json(output_dir / "portfolio.json") or {}
        for row in portfolio.get("holdings", []) or []:
            if _norm(row.get("symbol", "")) == sym:
                holding = row
                break

    title_bits = [sym]
    if holding and holding.get("role"):
        title_bits.append(str(holding["role"]).replace("_", " "))
    lines.append(" ".join(title_bits))
    lines.append("")

    overview: list[str] = []
    if holding:
        sources = holding.get("sources") or []
        if sources:
            overview.append(f"Agent sources: {', '.join(sources)}")
        if holding.get("score") is not None:
            overview.append(f"Composite agent score: {float(holding['score']):.2f}")
        if holding.get("confidence") is not None:
            overview.append(f"Confidence: {float(holding['confidence']):.0%}")
        if holding.get("weight_pct") is not None:
            overview.append(f"Target portfolio weight: {float(holding['weight_pct']):.2f}%")
        if holding.get("allocation_usd") is not None:
            overview.append(f"Target allocation: ${float(holding['allocation_usd']):,.2f}")
        if holding.get("price") is not None:
            overview.append(f"Reference price: ${float(holding['price']):,.2f}")
        if holding.get("projected_return_pct") is not None:
            overview.append(f"Projected return: {float(holding['projected_return_pct']):+.2f}%")
        if holding.get("rationale"):
            overview.append(f"Summary: {holding['rationale']}")
    elif day_position:
        overview.append("Intraday position — not a long-term portfolio holding.")
    elif current_position:
        overview.append("Held in your account but not in the current agent target portfolio.")
    else:
        overview.append("No active agent portfolio entry — analysis from latest agent reports.")
    lines.extend(_section("Overview", overview))

    preds = _prediction_rows(output_dir, sym)
    if preds:
        pred_lines = []
        for row in preds:
            direction = str(row.get("predicted_direction", "flat")).upper()
            ret = float(row.get("predicted_return_pct", 0))
            conf = float(row.get("confidence", 0))
            rank = row.get("rank", "—")
            pred_lines.append(
                f"• {row['horizon_label']}: {direction} {ret:+.2f}% "
                f"(confidence {conf:.0%}, rank #{rank})"
            )
            if row.get("order_type"):
                note = str(row["order_type"])
                if row.get("limit_price") is not None:
                    note += f" @ ${float(row['limit_price']):.2f}"
                pred_lines.append(f"  Order preference: {note}")
            if row.get("rationale"):
                pred_lines.append(f"  {row['rationale']}")
        lines.extend(_section("Market Predictor (fused agents)", pred_lines))

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
        lines.extend(_section("Finance Agent", fin_lines))

    mentions = _agent_mentions(output_dir, sym)
    if mentions:
        lines.extend(_section("Supporting agent reports", mentions[:12]))

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