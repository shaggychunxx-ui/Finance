"""Format Finance agent JSON outputs as readable report text."""

from __future__ import annotations

import json
from typing import Any


def _metric_label(key: str) -> str:
    return key.replace("_", " ").strip().title()


def _format_metric_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if abs(value) >= 1000 and value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(str(item) for item in value[:6])
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=True)[:80]
    return str(value)


def _format_metric_block(block: dict[str, Any]) -> list[str]:
    rows: list[tuple[str, str]] = []
    for key, value in block.items():
        if key.endswith("_label") or key in ("agent",):
            continue
        if value in (None, "", [], {}):
            continue
        rows.append((_metric_label(key), _format_metric_value(value)))
    if not rows:
        return []
    label_w = min(30, max(len(label) for label, _ in rows) + 1)
    return [f"  {label:<{label_w}}  {val}" for label, val in rows]


def format_report_summary(data: dict[str, Any]) -> str:
    lines: list[str] = []
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    kpis = data.get("kpis", {})

    agent = meta.get("agent", "Agent")
    lines.append(agent)
    lines.append("=" * min(60, len(agent) + 10))
    lines.append("")

    summary = meta.get("expert_summary") or meta.get("national_headline")
    if summary:
        lines.append(summary)
        lines.append("")

    metric_lines: list[str] = []
    for block in (metrics, kpis):
        metric_lines.extend(_format_metric_block(block))
    if metric_lines:
        lines.append("Key metrics")
        lines.append("-" * 42)
        lines.extend(metric_lines)
        lines.append("")

    label_keys = ("regime_label", "trend_label", "stress_label", "risk_label", "strength_label")
    labels = [metrics.get(k) or kpis.get(k) for k in label_keys if metrics.get(k) or kpis.get(k)]
    if labels:
        lines.append("")
        lines.append(f"  Regime: {labels[0]}")

    signals = data.get("market_signals", [])
    if signals:
        lines.append("")
        lines.append("Market signals:")
        for sig in signals[:8]:
            tickers = ", ".join(sig.get("tickers", []))
            lines.append(f"  • {sig.get('sector', '?')} [{sig.get('bias', '?')}] — {tickers}")
            reason = sig.get("reason", "")
            if reason:
                lines.append(f"    {reason}")

    recs = data.get("recommendations", [])
    if recs:
        lines.append("")
        lines.append("Recommendations:")
        for rec in recs[:8]:
            lines.append(f"  • {rec}")

    preds = data.get("predictions", {})
    if preds:
        lines.append("")
        for horizon, label in [("24h", "24 Hour"), ("1mo", "1 Month"), ("1yr", "1 Year")]:
            rows = preds.get(horizon, [])
            if not rows:
                continue
            lines.append(f"Top movers — {label}")
            lines.append("-" * 42)
            lines.append(f"  {'Rank':<5} {'Symbol':<8} {'Return':>9}  Direction")
            for row in rows[:8]:
                lines.append(
                    f"  #{row.get('rank', '?'):<4} "
                    f"{str(row.get('symbol', '?')):<8} "
                    f"{row.get('predicted_return_pct', 0):+8.2f}%  "
                    f"{row.get('predicted_direction', '?')}"
                )
            lines.append("")

    events = data.get("events", [])
    if events:
        lines.append("")
        lines.append("Recent events:")
        for event in events[:6]:
            lines.append(
                f"  • [{str(event.get('impact', '?')).upper()}] "
                f"{event.get('title', '')[:72]}"
            )

    return "\n".join(lines).strip() or json.dumps(data, indent=2)[:8000]