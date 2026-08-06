"""
E*TRADE IPO Mail Agent
======================
Reads **E*TRADE New Issue / IPO availability** emails (Gmail forward path) and
writes structured ``new_offerings[]`` for fusion / research.

E*TRADE New Issue Center is **not** in the broker API. SEC agents
``ipo-monitor`` / ``ipo-debut`` cover EDGAR only. This agent covers the
broker mail channel.

Unattended source (preferred):
  grok-shared-workspace ``work/gmail-api/`` with OAuth under ``~/.gmail-link/``

Interactive / fallback:
  Seed file ``output/etrade_ipo_mail_inbox.json`` (subjects/from/ids/snippets only).

Never logs full account numbers or OAuth tokens.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "output" / "etrade_ipo_mail.json"
DEFAULT_INBOX = ROOT / "output" / "etrade_ipo_mail_inbox.json"
# Written by Grok Gmail MCP / Sync-GmailIpoInbox so agents share the same mailbox view
GMAIL_CACHE = Path.home() / ".gmail-link" / "ipo_inbox_cache.json"
GMAIL_POLL_CANDIDATES = [
    Path.home() / "Documents" / "GitHub" / "grok-shared-workspace" / "work" / "gmail-api" / "poll_etrade_ipo.py",
]

# Subject / body patterns that indicate real New Issue Center mail (not trade fills).
IPO_SUBJECT_RE = re.compile(
    r"(new\s+ipo\s+available|new\s+issue\s+center|initial\s+public\s+offering|"
    r"\bipo\b.*available|available.*\bipo\b|new\s+issue)",
    re.I,
)
TRADE_ALERT_RE = re.compile(r"^executed:\s*(buy|sell)\b", re.I)


@dataclass
class MailOffering:
    message_id: str
    subject: str
    from_addr: str
    date: str
    snippet: str
    company: str | None = None
    ticker: str | None = None
    links: list[str] = field(default_factory=list)
    kind: str = "etrade-new-issue"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_inbox_file(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    if isinstance(data, dict):
        msgs = data.get("messages") or data.get("threads") or []
        out: list[dict[str, Any]] = []
        for item in msgs:
            if not isinstance(item, dict):
                continue
            if "messages" in item and isinstance(item["messages"], list):
                for m in item["messages"]:
                    if isinstance(m, dict):
                        out.append(m)
            else:
                out.append(item)
        return out
    return []


def _try_gmail_api_poll() -> list[dict[str, Any]]:
    """Run shared-bus poll script if OAuth token exists; never print secrets."""
    token = Path.home() / ".gmail-link" / "token.json"
    if not token.is_file():
        return []
    for script in GMAIL_POLL_CANDIDATES:
        if not script.is_file():
            continue
        try:
            report = script.parent / "reports" / "poll-latest.json"
            proc = subprocess.run(
                [sys.executable, str(script), "--out", str(report)],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(script.parent),
                check=False,
            )
            if proc.returncode != 0 and not report.is_file():
                continue
            # Prefer structured report written by poll_etrade_ipo.py
            data: dict[str, Any] | list[Any] | None = None
            if report.is_file():
                try:
                    data = json.loads(report.read_text(encoding="utf-8"))
                except Exception:
                    data = None
            if data is None and proc.stdout.strip():
                try:
                    data = json.loads(proc.stdout)
                except Exception:
                    continue
            if isinstance(data, dict) and data.get("ok") is False:
                continue
            if isinstance(data, dict):
                msgs = (
                    data.get("real_ipo_mail")
                    or data.get("candidates_sample")
                    or data.get("messages")
                    or data.get("hits")
                    or []
                )
                if isinstance(msgs, list) and msgs:
                    # normalize id fields for parse_messages
                    out: list[dict[str, Any]] = []
                    for m in msgs:
                        if not isinstance(m, dict):
                            continue
                        mid = m.get("id") or m.get("message_id")
                        out.append(
                            {
                                **m,
                                "message_id": mid,
                                "id": mid,
                                "from": m.get("from") or m.get("from_addr") or "",
                            }
                        )
                    return out
            if isinstance(data, list):
                return [m for m in data if isinstance(m, dict)]
        except Exception:
            continue
    return []


def _extract_links(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"https?://[^\s<>\"']+", text or "")))[:20]


def _guess_company_ticker(subject: str, snippet: str) -> tuple[str | None, str | None]:
    blob = f"{subject}\n{snippet}"
    # Common patterns: TICKER in parens, or "Company (TICKER)"
    m = re.search(r"\(([A-Z]{1,5})\)", blob)
    ticker = m.group(1) if m else None
    # Reject common false positives from prose (not real tickers)
    if ticker in {"IPO", "NEW", "THE", "AND", "FOR", "SEC", "USA", "PDF"}:
        ticker = None
    company = None
    m2 = re.search(
        r"(?:offering|IPO|issue)\s+(?:for|of|:)\s+([A-Z][A-Za-z0-9&.,' \-]{2,60})",
        blob,
        re.I,
    )
    if m2:
        company = m2.group(1).strip(" .,-")
    if not company and "new initial public offering" in snippet.lower():
        company = "See New Issue Center / prospectus (name in full email body)"
    return company, ticker


def parse_messages(raw_messages: list[dict[str, Any]]) -> list[MailOffering]:
    offerings: list[MailOffering] = []
    for m in raw_messages:
        subject = str(m.get("subject") or m.get("Subject") or "")
        from_addr = str(m.get("from") or m.get("From") or "")
        snippet = str(
            m.get("snippet")
            or m.get("body_preview")
            or m.get("body_text")
            or m.get("body")
            or ""
        )
        if TRADE_ALERT_RE.search(subject):
            continue
        etrade_ish = (
            "etrade" in from_addr.lower()
            or "e-trade" in from_addr.lower()
            or "etrade" in subject.lower()
            or "e*trade" in subject.lower()
            or "new issue" in subject.lower()
            or "ipo" in subject.lower()
        )
        if not etrade_ish and not IPO_SUBJECT_RE.search(subject + " " + snippet):
            continue
        if not IPO_SUBJECT_RE.search(subject + " " + snippet) and "new issue" not in snippet.lower():
            # Allow subject "New IPO available" style only
            if "ipo" not in subject.lower() and "new issue" not in subject.lower():
                continue
        company, ticker = _guess_company_ticker(subject, snippet)
        offerings.append(
            MailOffering(
                message_id=str(m.get("message_id") or m.get("id") or ""),
                subject=subject,
                from_addr=from_addr,
                date=str(m.get("date") or m.get("Date") or ""),
                snippet=snippet[:500],
                company=company,
                ticker=ticker,
                links=_extract_links(snippet),
            )
        )
    return offerings


class EtradeIpoMailAnalyst(BaseExpert):
    def __init__(self, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="etrade-ipo-mail")

    def collect_raw(self) -> tuple[list[dict[str, Any]], str]:
        # 1) Durable Gmail API (token.json) — preferred for unattended worker
        api_msgs = _try_gmail_api_poll()
        if api_msgs:
            return api_msgs, "gmail-api-poll"
        # 2) Grok Gmail MCP / session bridge (same mailbox Grok can read)
        for cache, label in (
            (GMAIL_CACHE, "gmail-mcp-cache"),
            (DEFAULT_INBOX, "seed-inbox-file"),
        ):
            inbox = _load_inbox_file(cache)
            if inbox:
                return inbox, label
        return [], "none"

    def analyze(self) -> dict[str, Any]:
        raw, source = self.collect_raw()
        offerings = parse_messages(raw)
        signals: list[dict[str, Any]] = []
        for o in offerings:
            signals.append(
                {
                    "type": "ipo_new_issue_mail",
                    "source": "etrade-mail",
                    "message_id": o.message_id,
                    "subject": o.subject,
                    "ticker": o.ticker,
                    "company": o.company,
                    "date": o.date,
                    "confidence": 0.7 if o.ticker or o.company else 0.55,
                    "note": "E*TRADE New Issue Center via Gmail; not broker API",
                }
            )
        recommendations: list[str] = []
        if offerings:
            recommendations.append(
                f"E*TRADE mail: {len(offerings)} New Issue/IPO notice(s). "
                "Cross-check SEC ipo-monitor/ipo-debut for filings; review New Issue Center before allocating."
            )
            recommendations.append(
                "Also see EDGAR agents ipo-monitor and ipo-debut for regulatory pipeline context."
            )
        else:
            recommendations.append(
                "No E*TRADE IPO/New Issue emails in current inbox seed or Gmail API poll. "
                "Ensure ~/.gmail-link/token.json for unattended poll, or refresh seed inbox."
            )
        return {
            "meta": {
                "agent": "E*TRADE IPO Mail",
                "agent_id": "etrade-ipo-mail",
                "analyzed_at": _utc_now(),
                "data_sources": [source],
                "mail_source_note": (
                    "Gmail path: (1) ~/.gmail-link/token.json + poll_etrade_ipo.py, "
                    "(2) ~/.gmail-link/ipo_inbox_cache.json synced from Grok Gmail MCP, "
                    "(3) output/etrade_ipo_mail_inbox.json seed. "
                    "If Grok can read Gmail, agents use the MCP cache bridge."
                ),
                "new_offerings_count": len(offerings),
                "temperature": self.temperature,
            },
            "summary": {
                "offerings_found": len(offerings),
                "source": source,
                "activity_label": (
                    "E*TRADE New Issue mail present" if offerings else "No IPO mail in sample"
                ),
            },
            "new_offerings": [
                {
                    "message_id": o.message_id,
                    "subject": o.subject,
                    "from": o.from_addr,
                    "date": o.date,
                    "company": o.company,
                    "ticker": o.ticker,
                    "links": o.links,
                    "snippet": o.snippet,
                    "kind": o.kind,
                }
                for o in offerings
            ],
            "market_signals": signals,
            "recommendations": self.append_memory_recommendations(recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.analyze()
        out = output or DEFAULT_OUTPUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def run_etrade_ipo_mail_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return EtradeIpoMailAnalyst(pipeline_context=pipeline_context).run(output=output)
