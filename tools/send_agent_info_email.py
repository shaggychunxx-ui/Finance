#!/usr/bin/env python3
"""Build a detailed agent-info PDF and email it to self.

Reads the GROMIT live runtime (%USERPROFILE%\\Finance), never the git clone
as the data source. Reuses the trader-summary Gmail send path (API / CDP /
Chrome Default compose + attach + ink gate).

Usage (live venv):
  python tools/send_agent_info_email.py
  python tools/send_agent_info_email.py --print-only
  python tools/send_agent_info_email.py --pdf-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from send_etrade_trader_summary_email import (  # noqa: E402
    DEFAULT_TO,
    live_root,
    send_summary,
)

SECRET_KEYS = frozenset(
    {
        "account_id_key",
        "consumer_key",
        "consumer_secret",
        "access_token",
        "access_token_secret",
        "bridge_token",
        "password",
        "secret",
        "token",
        "api_key",
    }
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(v: Any) -> str:
    n = _f(v)
    if n is None:
        return "-"
    return f"{n:.1f}%"


def _num(v: Any, digits: int = 3) -> str:
    n = _f(v)
    if n is None:
        return "-"
    return f"{n:.{digits}f}"


def _dt(raw: Any) -> str:
    if raw is None or raw == "":
        return "-"
    s = str(raw).replace("T", " ").replace("+00:00", " UTC")
    return s[:22]


def _xml(s: Any) -> str:
    return (
        str(s if s is not None else "-")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _strip_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_secrets(v) for k, v in obj.items() if str(k).lower() not in SECRET_KEYS}
    if isinstance(obj, list):
        return [_strip_secrets(v) for v in obj]
    return obj


def _signal_summary(signals: list[Any], *, limit: int = 3) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    suppressed = 0
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        bias = str(sig.get("bias") or "NEUTRAL").upper()
        if sig.get("learning_suppressed"):
            suppressed += 1
        counts[bias] += 1
        if bias in {"BULLISH", "BEARISH"} and not sig.get("learning_suppressed") and len(rows) < limit:
            tickers = [str(t).upper() for t in (sig.get("tickers") or [])[:6] if t]
            rows.append(
                {
                    "bias": bias,
                    "tickers": tickers,
                    "reason": str(sig.get("reason") or sig.get("sector") or "")[:90],
                    "confidence": _f(sig.get("confidence")),
                }
            )
    return {
        "bullish": int(counts.get("BULLISH") or 0),
        "bearish": int(counts.get("BEARISH") or 0),
        "neutral": int(counts.get("NEUTRAL") or 0),
        "suppressed": suppressed,
        "calls": rows,
    }


def _catalog_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from agents.platform_catalog import full_agent_catalog  # noqa: WPS433

        for entry in full_agent_catalog(check_remote=False):
            if not isinstance(entry, dict):
                continue
            rows.append(
                {
                    "id": str(entry.get("id") or ""),
                    "label": str(entry.get("label") or ""),
                    "category": str(entry.get("category") or ""),
                    "output": str(entry.get("output") or ""),
                    "personality": str(entry.get("personality") or ""),
                }
            )
    except Exception:
        pass
    return rows


def _group_meta(agent_id: str) -> dict[str, Any]:
    try:
        from agent_groups import agent_group, agent_group_id, agent_scoring_system

        g = agent_group(agent_id)
        scoring = agent_scoring_system(agent_id)
        return {
            "group_id": agent_group_id(agent_id),
            "group_label": str(g.get("label") or ""),
            "trading_role": str(g.get("trading_role") or ""),
            "scoring_mode": str(scoring.get("mode") or ""),
            "primary_metric": str(scoring.get("primary_metric") or ""),
        }
    except Exception:
        return {
            "group_id": "",
            "group_label": "",
            "trading_role": "",
            "scoring_mode": "",
            "primary_metric": "",
        }


def _last_pipeline(runs_payload: dict[str, Any]) -> dict[str, Any]:
    runs = [r for r in (runs_payload.get("runs") or []) if isinstance(r, dict)]
    if not runs:
        return {}
    last = runs[-1]
    full = last
    for row in reversed(runs):
        if int(row.get("agents_total") or 0) >= 20:
            full = row
            break
    return {
        "last_at": last.get("at"),
        "last_ok": last.get("agents_ok"),
        "last_total": last.get("agents_total"),
        "last_cycle": last.get("cycle_id"),
        "full_at": full.get("at"),
        "full_ok": full.get("agents_ok"),
        "full_total": full.get("agents_total"),
        "full_cycle": full.get("cycle_id"),
        "total_runs": runs_payload.get("total_runs") or len(runs),
    }


def gather_agent_info(root: Path) -> dict[str, Any]:
    out = root / "output"
    hist = out / "history"
    learning = _load_json(hist / "agent_learning.json")
    policy = _load_json(hist / "learning_policy.json")
    brief = _load_json(hist / "next_session_brief.json")
    accuracy = _load_json(hist / "prediction_accuracy.json")
    pending = _load_json(hist / "prediction_pending.json")
    runs = _load_json(hist / "pipeline_runs.json")
    refresh = _load_json(out / "phone_refresh_last.json")
    catalog = _catalog_rows(root)
    catalog_by_id = {str(r.get("id")): r for r in catalog if r.get("id")}

    agents_raw = learning.get("agents") if isinstance(learning.get("agents"), dict) else {}
    rows: list[dict[str, Any]] = []
    for aid, rec in agents_raw.items():
        if not isinstance(rec, dict):
            rec = {}
        agent_id = str(rec.get("agent_id") or aid)
        cat = catalog_by_id.get(agent_id) or {}
        gmeta = _group_meta(agent_id)
        output_name = str(cat.get("output") or f"{agent_id.replace('-', '_')}.json")
        report = _load_json(out / output_name)
        signals = report.get("market_signals") if isinstance(report.get("market_signals"), list) else []
        analyzed_at = None
        meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
        analyzed_at = meta.get("analyzed_at") or report.get("analyzed_at")
        expert = str(meta.get("expert_summary") or "")[:180]
        rows.append(
            {
                "agent_id": agent_id,
                "label": cat.get("label") or agent_id,
                "personality": cat.get("personality") or "",
                "category": cat.get("category") or gmeta.get("group_label") or "",
                "group_id": gmeta.get("group_id") or "",
                "group_label": gmeta.get("group_label") or "",
                "trading_role": gmeta.get("trading_role") or "",
                "scoring_mode": gmeta.get("scoring_mode") or "",
                "accuracy_pct": _f(rec.get("accuracy_pct")),
                "live_accuracy_pct": _f(rec.get("live_accuracy_pct")),
                "proxy_accuracy_pct": _f(rec.get("proxy_accuracy_pct")),
                "edge_score": _f(rec.get("edge_score")),
                "proxy_edge_score": _f(rec.get("proxy_edge_score")),
                "fusion_multiplier": _f(rec.get("fusion_multiplier")),
                "confidence_scale": _f(rec.get("confidence_scale")),
                "posture": rec.get("posture") or "-",
                "preferred_horizon": rec.get("preferred_horizon") or "-",
                "family": rec.get("family") or "",
                "source": rec.get("source") or "",
                "sample_trials": int(rec.get("sample_trials") or 0),
                "live_sample_trials": int(rec.get("live_sample_trials") or 0),
                "proxy_sample_trials": int(rec.get("proxy_sample_trials") or 0),
                "avg_net_return_pct": _f(rec.get("avg_net_return_pct")),
                "lessons": [str(x) for x in (rec.get("lessons") or [])[:3]],
                "trust_symbols": [str(x).upper() for x in (rec.get("trust_symbols") or [])[:8]],
                "avoid_symbols": [str(x).upper() for x in (rec.get("avoid_symbols") or [])[:8]],
                "analyzed_at": analyzed_at,
                "expert_summary": expert,
                "signals": _signal_summary(signals),
            }
        )

    # Catalog agents with no learning row yet.
    known = {r["agent_id"] for r in rows}
    for cat in catalog:
        aid = str(cat.get("id") or "")
        if not aid or aid in known:
            continue
        gmeta = _group_meta(aid)
        rows.append(
            {
                "agent_id": aid,
                "label": cat.get("label") or aid,
                "personality": cat.get("personality") or "",
                "category": cat.get("category") or gmeta.get("group_label") or "",
                "group_id": gmeta.get("group_id") or "",
                "group_label": gmeta.get("group_label") or "",
                "trading_role": gmeta.get("trading_role") or "",
                "scoring_mode": gmeta.get("scoring_mode") or "",
                "accuracy_pct": None,
                "live_accuracy_pct": None,
                "proxy_accuracy_pct": None,
                "edge_score": None,
                "proxy_edge_score": None,
                "fusion_multiplier": None,
                "confidence_scale": None,
                "posture": "untracked",
                "preferred_horizon": "-",
                "family": "",
                "source": "",
                "sample_trials": 0,
                "live_sample_trials": 0,
                "proxy_sample_trials": 0,
                "avg_net_return_pct": None,
                "lessons": [],
                "trust_symbols": [],
                "avoid_symbols": [],
                "analyzed_at": None,
                "expert_summary": "",
                "signals": _signal_summary([]),
            }
        )

    rows.sort(
        key=lambda r: (
            -(r.get("accuracy_pct") if r.get("accuracy_pct") is not None else -1),
            -(r.get("edge_score") if r.get("edge_score") is not None else -1),
            str(r.get("agent_id") or ""),
        )
    )

    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        gid = str(r.get("group_id") or "unknown")
        g = groups.setdefault(
            gid,
            {
                "group_id": gid,
                "label": r.get("group_label") or gid,
                "count": 0,
                "acc": [],
                "edge": [],
                "role": r.get("trading_role") or "",
                "mode": r.get("scoring_mode") or "",
            },
        )
        g["count"] += 1
        if r.get("accuracy_pct") is not None:
            g["acc"].append(float(r["accuracy_pct"]))
        if r.get("edge_score") is not None:
            g["edge"].append(float(r["edge_score"]))
    group_rows = []
    for g in groups.values():
        accs = g.pop("acc")
        edges = g.pop("edge")
        g["avg_accuracy_pct"] = round(sum(accs) / len(accs), 1) if accs else None
        g["avg_edge"] = round(sum(edges) / len(edges), 4) if edges else None
        group_rows.append(g)
    group_rows.sort(key=lambda g: (-(g.get("avg_accuracy_pct") or -1), str(g.get("label"))))

    pending_preds = [p for p in (pending.get("predictions") or []) if isinstance(p, dict)]
    scored = accuracy.get("scored") if isinstance(accuracy.get("scored"), list) else []
    acc_agents = accuracy.get("agents") if isinstance(accuracy.get("agents"), dict) else {}
    live_scored_acc = sum(int((v or {}).get("live_scored") or 0) for v in acc_agents.values() if isinstance(v, dict))

    directional = []
    for r in rows:
        for call in (r.get("signals") or {}).get("calls") or []:
            directional.append(
                {
                    "agent_id": r.get("agent_id"),
                    "bias": call.get("bias"),
                    "tickers": call.get("tickers") or [],
                    "reason": call.get("reason") or "",
                    "confidence": call.get("confidence"),
                }
            )

    now = datetime.now(timezone.utc)
    meta = learning.get("meta") if isinstance(learning.get("meta"), dict) else {}
    return _strip_secrets(
        {
            "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
            "host": os.environ.get("COMPUTERNAME") or "GROMIT",
            "catalog_count": len(catalog) or len(rows),
            "learning_count": int(meta.get("agents_tracked") or len(agents_raw)),
            "phone_agent_count": refresh.get("agent_count"),
            "learning_updated_at": meta.get("updated_at"),
            "live_scored_rows": int(meta.get("live_scored_rows") or 0),
            "backtest_trial_rows_merged": int(meta.get("backtest_trial_rows_merged") or 0),
            "trial_cycle": ((meta.get("trial_journal") or {}) if isinstance(meta.get("trial_journal"), dict) else {}).get(
                "cycle_id"
            ),
            "pending_predictions": len(pending_preds),
            "scored_rows": len(scored) if scored else int(accuracy.get("pending_count") or 0),
            "live_scored_accuracy": live_scored_acc,
            "boost_agents": list(policy.get("boost_agents") or []),
            "cut_agents": list(policy.get("cut_agents") or []),
            "policy_updated_at": policy.get("updated_at"),
            "brief_for": brief.get("for_session"),
            "brief_updated_at": brief.get("updated_at"),
            "brief_benchmark": str(brief.get("benchmark_summary") or "")[:400],
            "brief_actions": [str(a) for a in (brief.get("actions") or [])[:8]],
            "top_agents": [
                {
                    "agent_id": str(a.get("agent_id") or ""),
                    "accuracy_pct": a.get("accuracy_pct"),
                    "edge_score": a.get("edge_score"),
                    "posture": a.get("posture"),
                    "preferred_horizon": a.get("preferred_horizon"),
                    "fusion_multiplier": a.get("fusion_multiplier"),
                }
                for a in (brief.get("top_agents") or [])[:8]
                if isinstance(a, dict)
            ],
            "weak_agents": [
                {
                    "agent_id": str(a.get("agent_id") or ""),
                    "accuracy_pct": a.get("accuracy_pct"),
                    "edge_score": a.get("edge_score"),
                    "posture": a.get("posture"),
                    "fusion_multiplier": a.get("fusion_multiplier"),
                    "lessons": [str(x) for x in (a.get("lessons") or [])[:2]],
                }
                for a in (brief.get("weak_agents") or [])[:8]
                if isinstance(a, dict)
            ],
            "pipeline": _last_pipeline(runs),
            "groups": group_rows,
            "agents": rows,
            "directional_calls": directional[:40],
        }
    )


def format_subject(data: dict[str, Any]) -> str:
    top = (data.get("top_agents") or [{}])[0] if data.get("top_agents") else {}
    top_id = top.get("agent_id") or "-"
    top_acc = _pct(top.get("accuracy_pct"))
    n = data.get("learning_count") or data.get("catalog_count") or len(data.get("agents") or [])
    return (
        f"E*TRADE agent info PDF {data.get('generated_at', '')}  "
        f"{n} agents  top {top_id} {top_acc}"
    )


def format_text(data: dict[str, Any]) -> str:
    pipe = data.get("pipeline") or {}
    lines = [
        f"E*TRADE agent info — {data.get('generated_at')}",
        f"Host {data.get('host')}",
        "",
        "== Roster ==",
        (
            f"Catalog {data.get('catalog_count')}  learning {data.get('learning_count')}  "
            f"phone pack {data.get('phone_agent_count') or '-'}"
        ),
        f"Learning updated {_dt(data.get('learning_updated_at'))}",
        (
            f"Live scored rows {data.get('live_scored_rows')}  "
            f"walk-forward merged {data.get('backtest_trial_rows_merged')}  "
            f"pending predictions {data.get('pending_predictions')}"
        ),
        f"Trial cycle {data.get('trial_cycle') or '-'}",
        (
            "Note: live 24h labels are still 0 — accuracy/edge below are walk-forward "
            "benchmark + sticky live_accuracy, not matured live trades."
        ),
        "",
        "== Pipeline ==",
        (
            f"Last cycle {pipe.get('last_cycle') or '-'}  "
            f"{pipe.get('last_ok')}/{pipe.get('last_total')} ok  {_dt(pipe.get('last_at'))}"
        ),
        (
            f"Last full-ish {pipe.get('full_cycle') or '-'}  "
            f"{pipe.get('full_ok')}/{pipe.get('full_total')} ok  {_dt(pipe.get('full_at'))}"
        ),
        f"Recorded runs {pipe.get('total_runs') or '-'}",
        "",
        "== Next session ==",
        f"For {data.get('brief_for') or '-'}  updated {_dt(data.get('brief_updated_at'))}",
        data.get("brief_benchmark") or "(no benchmark)",
    ]
    for a in data.get("brief_actions") or []:
        lines.append(f"- {a}")
    boost = data.get("boost_agents") or []
    cut = data.get("cut_agents") or []
    lines += [
        "",
        "== Policy ==",
        f"Boost: {', '.join(boost) if boost else '(none)'}",
        f"Cut: {', '.join(cut) if cut else '(none)'}",
        "",
        "== Groups (avg walk-forward acc) ==",
    ]
    for g in data.get("groups") or []:
        lines.append(
            f"{(g.get('label') or g.get('group_id')):<32}  n={g.get('count'):>2}  "
            f"acc {_pct(g.get('avg_accuracy_pct')):>6}  edge {_num(g.get('avg_edge'), 3):>6}  "
            f"{g.get('role') or '-'} / {g.get('mode') or '-'}"
        )
    lines += ["", "== Top agents =="]
    for a in data.get("top_agents") or []:
        lines.append(
            f"{a.get('agent_id'):<22}  acc {_pct(a.get('accuracy_pct')):>6}  "
            f"edge {_num(a.get('edge_score'), 3):>6}  fusion {_num(a.get('fusion_multiplier'), 3):>6}  "
            f"{a.get('posture') or '-'}  {a.get('preferred_horizon') or '-'}"
        )
    lines += ["", "== Weak agents =="]
    weak = data.get("weak_agents") or []
    if not weak:
        lines.append("(none)")
    for a in weak:
        lesson = (a.get("lessons") or ["-"])[0]
        lines.append(
            f"{a.get('agent_id'):<22}  acc {_pct(a.get('accuracy_pct')):>6}  "
            f"edge {_num(a.get('edge_score'), 3):>6}  {a.get('posture') or '-'}  {lesson[:70]}"
        )
    lines += ["", "== Current directional calls (not suppressed) =="]
    calls = data.get("directional_calls") or []
    if not calls:
        lines.append("(none — agents NEUTRAL or learning_suppressed)")
    for c in calls[:24]:
        tickers = ",".join(c.get("tickers") or []) or "-"
        lines.append(
            f"{c.get('agent_id'):<22}  {c.get('bias'):<8}  {tickers:<24}  {str(c.get('reason') or '')[:60]}"
        )
    lines += ["", "== All agents =="]
    for r in data.get("agents") or []:
        lines.append(
            f"{r.get('agent_id'):<22}  {_pct(r.get('accuracy_pct')):>6}  "
            f"edge {_num(r.get('edge_score'), 3):>6}  fus {_num(r.get('fusion_multiplier'), 3):>6}  "
            f"{str(r.get('posture') or '-'):<12}  {(r.get('group_label') or r.get('group_id') or '-')[:28]}"
        )
    lines += [
        "",
        "No tokens / account_id_key in this mail. Generated on GROMIT live runtime.",
    ]
    return "\n".join(lines) + "\n"


def format_email_body(data: dict[str, Any], pdf_name: str) -> str:
    header = (
        f"Detailed agent-info PDF attached: {pdf_name}\n"
        "Roster, groups, accuracy, policy, and current calls below if the attachment is stripped.\n\n"
    )
    return header + format_text(data)


def build_agent_info_pdf(data: dict[str, Any], path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    base = getSampleStyleSheet()
    title = ParagraphStyle("T", parent=base["Title"], fontSize=16, leading=20, spaceAfter=6)
    h = ParagraphStyle(
        "H",
        parent=base["Heading2"],
        fontSize=11,
        leading=14,
        spaceBefore=10,
        spaceAfter=4,
        textColor=colors.HexColor("#1e3a5f"),
    )
    body = ParagraphStyle("B", parent=base["Normal"], fontSize=8.5, leading=11, spaceAfter=3)
    td = ParagraphStyle("TD", parent=base["Normal"], fontSize=7, leading=9)
    th = ParagraphStyle(
        "TH",
        parent=base["Normal"],
        fontSize=7,
        leading=9,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )
    note = ParagraphStyle(
        "N", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#64748b")
    )

    def cell(text: Any, header: bool = False) -> Paragraph:
        return Paragraph(_xml(text), th if header else td)

    def grid(rows: list[list[Any]], widths: list[float]) -> Table:
        data_rows: list[list[Paragraph]] = []
        for i, row in enumerate(rows):
            data_rows.append([cell(c, header=(i == 0)) for c in row])
        t = Table(data_rows, colWidths=widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.HexColor("#f8fafc"), colors.HexColor("#eef2ff")],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        return t

    pipe = data.get("pipeline") or {}
    story: list[Any] = [
        Paragraph("E*TRADE agent info", title),
        Paragraph(
            f"{_xml(data.get('generated_at'))} · {_xml(data.get('host'))} · "
            f"catalog {data.get('catalog_count')} · learning {data.get('learning_count')}",
            note,
        ),
        HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=8),
        Paragraph("Learning health", h),
        grid(
            [
                ["Metric", "Value"],
                ["Phone pack agents", data.get("phone_agent_count") or "-"],
                ["Learning tracked", data.get("learning_count")],
                ["Catalog", data.get("catalog_count")],
                ["Live scored rows", data.get("live_scored_rows")],
                ["Walk-forward merged", data.get("backtest_trial_rows_merged")],
                ["Pending predictions", data.get("pending_predictions")],
                ["Trial cycle", data.get("trial_cycle") or "-"],
                ["Learning updated", _dt(data.get("learning_updated_at"))],
            ],
            [2.4 * inch, 4.8 * inch],
        ),
        Paragraph(
            "Live 24h labels are still 0. Accuracy and edge in this mail are walk-forward "
            "benchmark plus sticky live_accuracy — not matured live trades.",
            body,
        ),
        Paragraph("Pipeline", h),
        Paragraph(
            f"Last { _xml(pipe.get('last_cycle') or '-') } "
            f"{pipe.get('last_ok')}/{pipe.get('last_total')} ok · {_xml(_dt(pipe.get('last_at')))}",
            body,
        ),
        Paragraph(
            f"Last full-ish { _xml(pipe.get('full_cycle') or '-') } "
            f"{pipe.get('full_ok')}/{pipe.get('full_total')} ok · {_xml(_dt(pipe.get('full_at')))}",
            body,
        ),
        Paragraph("Next session", h),
        Paragraph(
            f"For {_xml(data.get('brief_for') or '-')} · updated {_xml(_dt(data.get('brief_updated_at')))}",
            body,
        ),
        Paragraph(_xml(data.get("brief_benchmark") or "(no benchmark)"), body),
    ]
    for a in data.get("brief_actions") or []:
        story.append(Paragraph(f"• {_xml(a)}", body))
    boost = data.get("boost_agents") or []
    cut = data.get("cut_agents") or []
    story += [
        Paragraph("Policy", h),
        Paragraph(f"Boost: {_xml(', '.join(boost) if boost else '(none)')}", body),
        Paragraph(f"Cut: {_xml(', '.join(cut) if cut else '(none)')}", body),
        Paragraph("Groups", h),
    ]
    g_rows = [["Group", "n", "Avg acc", "Avg edge", "Role", "Scoring"]]
    for g in data.get("groups") or []:
        g_rows.append(
            [
                g.get("label") or g.get("group_id"),
                g.get("count"),
                _pct(g.get("avg_accuracy_pct")),
                _num(g.get("avg_edge"), 3),
                g.get("role") or "-",
                g.get("mode") or "-",
            ]
        )
    if len(g_rows) == 1:
        g_rows.append(["(none)", "-", "-", "-", "-", "-"])
    story.append(grid(g_rows, [1.9 * inch, 0.5 * inch, 0.8 * inch, 0.8 * inch, 1.1 * inch, 2.1 * inch]))
    story.append(Paragraph("Top agents", h))
    t_rows = [["Agent", "Acc", "Edge", "Fusion", "Posture", "Horizon"]]
    for a in data.get("top_agents") or []:
        t_rows.append(
            [
                a.get("agent_id"),
                _pct(a.get("accuracy_pct")),
                _num(a.get("edge_score"), 3),
                _num(a.get("fusion_multiplier"), 3),
                a.get("posture") or "-",
                a.get("preferred_horizon") or "-",
            ]
        )
    if len(t_rows) == 1:
        t_rows.append(["(none)", "-", "-", "-", "-", "-"])
    story.append(grid(t_rows, [1.7 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 1.2 * inch, 1.1 * inch]))
    story.append(Paragraph("Weak agents", h))
    w_rows = [["Agent", "Acc", "Edge", "Posture", "Lesson"]]
    for a in data.get("weak_agents") or []:
        w_rows.append(
            [
                a.get("agent_id"),
                _pct(a.get("accuracy_pct")),
                _num(a.get("edge_score"), 3),
                a.get("posture") or "-",
                (a.get("lessons") or ["-"])[0][:80],
            ]
        )
    if len(w_rows) == 1:
        w_rows.append(["(none)", "-", "-", "-", "-"])
    story.append(grid(w_rows, [1.5 * inch, 0.7 * inch, 0.7 * inch, 1.0 * inch, 3.3 * inch]))
    story.append(Paragraph("Current directional calls", h))
    c_rows = [["Agent", "Bias", "Tickers", "Reason"]]
    for c in data.get("directional_calls") or []:
        c_rows.append(
            [
                c.get("agent_id"),
                c.get("bias"),
                ",".join(c.get("tickers") or []) or "-",
                c.get("reason") or "-",
            ]
        )
    if len(c_rows) == 1:
        c_rows.append(["(none)", "-", "-", "NEUTRAL or learning_suppressed"])
    story.append(grid(c_rows[:25], [1.6 * inch, 0.9 * inch, 1.6 * inch, 3.1 * inch]))
    story.append(Paragraph("All agents", h))
    a_rows = [["Agent", "Acc", "Live", "Proxy", "Edge", "Fus", "Posture", "Group"]]
    for r in data.get("agents") or []:
        a_rows.append(
            [
                r.get("agent_id"),
                _pct(r.get("accuracy_pct")),
                _pct(r.get("live_accuracy_pct")),
                _pct(r.get("proxy_accuracy_pct")),
                _num(r.get("edge_score"), 3),
                _num(r.get("fusion_multiplier"), 3),
                r.get("posture") or "-",
                (r.get("group_label") or r.get("group_id") or "-")[:22],
            ]
        )
    if len(a_rows) == 1:
        a_rows.append(["(none)", "-", "-", "-", "-", "-", "-", "-"])
    story.append(
        grid(
            a_rows,
            [1.35 * inch, 0.6 * inch, 0.6 * inch, 0.65 * inch, 0.6 * inch, 0.55 * inch, 0.95 * inch, 1.9 * inch],
        )
    )
    detail = [r for r in (data.get("agents") or []) if r.get("lessons") or r.get("trust_symbols") or r.get("avoid_symbols")]
    if detail:
        story.append(Paragraph("Lessons / trust / avoid", h))
        d_rows = [["Agent", "Lessons", "Trust", "Avoid"]]
        for r in detail[:40]:
            d_rows.append(
                [
                    r.get("agent_id"),
                    " | ".join(r.get("lessons") or [])[:140] or "-",
                    ",".join(r.get("trust_symbols") or []) or "-",
                    ",".join(r.get("avoid_symbols") or []) or "-",
                ]
            )
        story.append(grid(d_rows, [1.4 * inch, 3.6 * inch, 1.1 * inch, 1.1 * inch]))
    story += [
        Spacer(1, 10),
        Paragraph("No tokens / account_id_key in this PDF. Generated on GROMIT live runtime.", note),
    ]
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title="E*TRADE agent info",
        author="GROMIT Finance",
        pageCompression=0,
    )
    doc.build(story)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Email detailed live agent info to self")
    parser.add_argument("--to", default=DEFAULT_TO)
    parser.add_argument("--print-only", action="store_true")
    parser.add_argument("--pdf-only", action="store_true")
    args = parser.parse_args(argv)

    root = live_root()
    data = gather_agent_info(root)
    subject = format_subject(data)
    pdf_path = root / "output" / "etrade_agent_info.pdf"
    build_agent_info_pdf(data, pdf_path)
    body = format_email_body(data, pdf_path.name)
    out_path = root / "output" / "etrade_agent_info_last.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"LIVE root: {root}")
    print(f"Subject: {subject}")
    print(f"Wrote {out_path}")
    print(f"Wrote {pdf_path} ({pdf_path.stat().st_size} bytes)")
    if args.print_only or args.pdf_only:
        print(body)
        return 0
    result = send_summary(
        args.to,
        subject,
        body,
        root / "output" / "chrome-oauth-debug",
        pdf_path,
    )
    result["pdf"] = str(pdf_path)
    result["pdf_bytes"] = pdf_path.stat().st_size
    safe = {k: v for k, v in result.items() if k != "opened"}
    print(json.dumps(safe, default=str))
    result_path = root / "output" / "etrade_agent_info_send.json"
    result_path.write_text(json.dumps(safe, indent=2, default=str) + "\n", encoding="utf-8")
    if not result.get("ok"):
        print("SEND FAIL", result.get("error"), file=sys.stderr)
        return 1
    print(f"SENT via {result.get('method')} to {args.to} pdf={pdf_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
