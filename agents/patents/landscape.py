"""Patent landscape research: holders, intended/possible uses, industry, market overlay.

The primary look-at is the company that holds the patent (assignee / listed
ticker when public). ETF tickers (XLV, QQQ, …) are only a sector overlay for
fusion — they are not a substitute for the holder.
"""

from __future__ import annotations

from typing import Any

# Sector -> industry, intended use, adjacent uses, ETF impact channels.
SECTOR_LANDSCAPE: dict[str, dict[str, Any]] = {
    "semiconductor": {
        "industry": "Semiconductors and electronics manufacturing",
        "intended": "Chip design, fabrication, packaging, or lithography of the claimed device/process",
        "possible": [
            "AI/GPU accelerators and high-bandwidth memory",
            "Foundry process nodes and yield tools",
            "Automotive and industrial power electronics",
        ],
        "impacts": [
            {"sector": "Technology", "tickers": ["XLK", "QQQ"], "bias": "BULLISH",
             "reason": "Process/device IP supports semiconductor capex and growth risk appetite"},
        ],
    },
    "artificial-intelligence": {
        "industry": "Software, cloud, and AI systems",
        "intended": "Model architecture, training, inference, or data-pipeline methods claimed in the filing",
        "possible": [
            "Enterprise copilot and search products",
            "On-device inference and edge silicon pairing",
            "Autonomous systems and industrial inspection",
        ],
        "impacts": [
            {"sector": "Growth / Tech", "tickers": ["QQQ", "XLK"], "bias": "BULLISH",
             "reason": "AI method IP is a growth-capex and software multiple signal"},
        ],
    },
    "biotechnology": {
        "industry": "Biopharma and life sciences",
        "intended": "Therapeutic, diagnostic, delivery, or manufacturing method for the claimed biology",
        "possible": [
            "Follow-on indications in the same disease family",
            "Platform licensing to larger pharma",
            "Companion diagnostics and manufacturing scale-up",
        ],
        "impacts": [
            {"sector": "Healthcare", "tickers": ["XLV", "QQQ"], "bias": "NEUTRAL",
             "reason": "Composition/method patents set exclusivity and pipeline optionality"},
        ],
    },
    "energy": {
        "industry": "Energy, storage, and materials",
        "intended": "Generation, storage, conversion, or materials process claimed in the filing",
        "possible": [
            "Grid-scale storage and EV pack chemistry",
            "Industrial heat and hydrogen",
            "Critical-mineral processing",
        ],
        "impacts": [
            {"sector": "Energy / Tech", "tickers": ["XLE", "XLK"], "bias": "NEUTRAL",
             "reason": "Storage and generation IP feeds energy-transition and commodity transmission"},
        ],
    },
    "automotive": {
        "industry": "Autos, mobility, and industrial machinery",
        "intended": "Powertrain, autonomy sensors, or vehicle-control methods",
        "possible": [
            "Robotaxi / ADAS stacks",
            "Commercial EV fleets",
            "Supplier licensing of drivetrain IP",
        ],
        "impacts": [
            {"sector": "Industrials", "tickers": ["XLI", "SPY"], "bias": "NEUTRAL",
             "reason": "Mobility IP is an industrial-cycle and auto-capex signal"},
        ],
    },
    "telecom": {
        "industry": "Communications equipment and networks",
        "intended": "Wireless, optical, or network protocol implementation",
        "possible": [
            "5G/6G infrastructure and SEPs",
            "Satellite and backhaul",
            "Standards licensing programs",
        ],
        "impacts": [
            {"sector": "Communications", "tickers": ["XLC", "SPY"], "bias": "NEUTRAL",
             "reason": "Standards-essential IP can reprice comms equipment and carriers"},
        ],
    },
    "fintech": {
        "industry": "Consumer finance and digital banking",
        "intended": "Origination, servicing, payments, identity, or credit-decision methods",
        "possible": [
            "AI underwriting and fraud models",
            "Account-opening KYC and ledger systems",
            "Loan marketplace and brokerage bundling",
        ],
        "impacts": [
            {"sector": "Financials", "tickers": ["XLF", "QQQ"], "bias": "NEUTRAL",
             "reason": "Fintech process IP is a financials + digital-finance growth overlay"},
        ],
    },
    "general": {
        "industry": "Cross-industry innovation",
        "intended": "The claimed apparatus, composition, or method as titled",
        "possible": ["Licensing, defensive portfolio, or product feature lock-in"],
        "impacts": [
            {"sector": "Broad Market", "tickers": ["SPY"], "bias": "NEUTRAL",
             "reason": "No concentrated industry read from title/assignee"},
        ],
    },
}

# Assignee substring -> (company, sector, listed ticker or "")
ASSIGNEE_COMPANY: list[tuple[str, str, str, str]] = [
    ("nvidia", "NVIDIA", "semiconductor", "NVDA"),
    ("tsmc", "TSMC", "semiconductor", "TSM"),
    ("taiwan semiconductor", "TSMC", "semiconductor", "TSM"),
    ("samsung", "Samsung Electronics", "semiconductor", ""),
    ("intel", "Intel", "semiconductor", "INTC"),
    ("asml", "ASML", "semiconductor", "ASML"),
    ("microsoft", "Microsoft", "artificial-intelligence", "MSFT"),
    ("google", "Alphabet", "artificial-intelligence", "GOOGL"),
    ("alphabet", "Alphabet", "artificial-intelligence", "GOOGL"),
    ("openai", "OpenAI", "artificial-intelligence", ""),
    ("amazon", "Amazon", "artificial-intelligence", "AMZN"),
    ("meta", "Meta", "artificial-intelligence", "META"),
    ("tesla", "Tesla", "automotive", "TSLA"),
    ("moderna", "Moderna", "biotechnology", "MRNA"),
    ("pfizer", "Pfizer", "biotechnology", "PFE"),
    ("amgen", "Amgen", "biotechnology", "AMGN"),
    ("regeneron", "Regeneron", "biotechnology", "REGN"),
    ("bristol", "Bristol Myers Squibb", "biotechnology", "BMY"),
    ("hengrui", "Hengrui Pharma / licensees", "biotechnology", ""),
    ("sofi", "SoFi Technologies", "fintech", "SOFI"),
    ("braveheart", "Braveheart Bio", "biotechnology", "BRVE"),
    ("qualcomm", "Qualcomm", "telecom", "QCOM"),
    ("ericsson", "Ericsson", "telecom", "ERIC"),
    ("huawei", "Huawei", "telecom", ""),
]

# Held-lot research when the live book is known (GROMIT snapshot).
HOLDING_LANDSCAPE: dict[str, dict[str, Any]] = {
    "BRVE": {
        "company": "Braveheart Bio",
        "industry": "Clinical-stage biopharma (cardiovascular)",
        "sector": "biotechnology",
        "title": "Cardiac myosin inhibitor franchise (BHB-1893 / HRS-1893) for hypertrophic cardiomyopathy",
        "intended": "Oral small-molecule cardiac myosin inhibitor for obstructive and non-obstructive HCM",
        "possible": [
            "Broader cardiomyopathy and heart-failure indications",
            "Combo or sequential use vs Camzyos-class CMIs",
            "License/manufacturing IP around the Hengrui-origin compound",
        ],
        "impacts": [
            {"sector": "Healthcare", "tickers": ["XLV", "QQQ"], "bias": "NEUTRAL",
             "reason": "HCM CMI IP and trial exclusivity can reprice biotech risk appetite (XLV/QQQ), not only the name"},
        ],
    },
    "SOFI": {
        "company": "SoFi Technologies",
        "industry": "Consumer fintech / digital banking",
        "sector": "fintech",
        "title": "Digital origination, banking, and brokerage product stack",
        "intended": "Student-loan, personal-loan, deposit, and brokerage workflows",
        "possible": [
            "Model-driven underwriting and collections",
            "Payments rails and account-opening KYC",
            "Cross-sell of crypto, advice, and workplace benefits",
        ],
        "impacts": [
            {"sector": "Financials", "tickers": ["XLF", "QQQ"], "bias": "NEUTRAL",
             "reason": "Consumer-fintech process IP is a financials + growth overlay if origination scales"},
        ],
    },
}


def company_from_assignee(assignee: str, sector: str) -> tuple[str, str, str]:
    """Return (company name, sector key, holder ticker or empty)."""
    raw = str(assignee or "").strip()
    lower = raw.lower()
    for needle, company, mapped_sector, ticker in ASSIGNEE_COMPANY:
        if needle in lower:
            return company, mapped_sector, ticker
    if raw:
        return raw, sector, ""
    return "Unnamed assignee", sector, ""


def _holder_block(company: str, ticker: str) -> dict[str, Any]:
    tick = str(ticker or "").upper().strip()
    return {
        "company": company,
        "ticker": tick,
        "listed": bool(tick),
    }


def research_finding(
    *,
    title: str,
    assignee: str = "",
    sector: str = "general",
    description: str = "",
    holder_ticker: str = "",
) -> dict[str, Any]:
    """Fill holder company/ticker plus uses, industry, and ETF sector overlay."""
    sec = sector if sector in SECTOR_LANDSCAPE else "general"
    company, mapped, mapped_ticker = company_from_assignee(assignee, sec)
    if mapped in SECTOR_LANDSCAPE:
        sec = mapped
    play = SECTOR_LANDSCAPE[sec]
    intended = str(play["intended"])
    title_l = f"{title} {description}".strip()
    if title_l:
        intended = f"{intended}. Filing focus: {title.strip()[:160]}"
    ticker = str(holder_ticker or mapped_ticker or "").upper().strip()
    holder = _holder_block(company, ticker)
    return attach_impact_window({
        "title": title.strip(),
        "company": company,
        "holder_ticker": ticker,
        "holders": [holder],
        "industry": str(play["industry"]),
        "sector": sec,
        "intended_use": intended,
        "possible_uses": list(play["possible"]),
        "market_impacts": [dict(row) for row in play["impacts"]],
        "assignee": str(assignee or company),
    })


def holdings_landscape(symbols: list[str]) -> list[dict[str, Any]]:
    """Research cards for live brokerage lots (company, uses, industry, market)."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = str(raw or "").upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        known = HOLDING_LANDSCAPE.get(sym)
        if not known:
            continue
        cards.append(
            attach_impact_window(
                {
                    "title": known["title"],
                    "symbol": sym,
                    "company": known["company"],
                    "holder_ticker": sym,
                    "holders": [_holder_block(known["company"], sym)],
                    "industry": known["industry"],
                    "sector": known["sector"],
                    "intended_use": known["intended"],
                    "possible_uses": list(known["possible"]),
                    "market_impacts": [dict(row) for row in known["impacts"]],
                    "assignee": known["company"],
                    "source": "held-lot landscape",
                }
            )
        )
    return cards


# Short = news/product catalyst. Long = exclusivity / process / platform.
IMPACT_WINDOWS = {
    "short": ("24h", "1wk"),
    "long": ("1mo", "1yr"),
}


def terms_for_card(card: dict[str, Any]) -> tuple[str, ...]:
    """Which impact windows this innovation can feed the pipeline."""
    source = str(card.get("source") or "")
    sector = str(card.get("sector") or "")
    if source.startswith("held-lot"):
        return ("short", "long")
    if source.lower() in {"ipwatchdog", "proxy"} and sector in {
        "artificial-intelligence",
        "fintech",
        "telecom",
        "automotive",
    }:
        return ("short", "long")
    if sector in {"semiconductor", "biotechnology", "energy"}:
        return ("long",)
    return ("long",)


def attach_impact_window(card: dict[str, Any]) -> dict[str, Any]:
    """Stamp short/long windows. The pipeline, not this agent, predicts price."""
    terms = list(terms_for_card(card))
    card["impact_terms"] = terms
    card["impact_windows"] = {t: list(IMPACT_WINDOWS[t]) for t in terms if t in IMPACT_WINDOWS}
    return card


def format_holder_label(card: dict[str, Any]) -> str:
    company = str(card.get("company") or card.get("assignee") or "Unknown holder")
    tick = str(card.get("holder_ticker") or card.get("symbol") or "").upper().strip()
    if not tick:
        holders = card.get("holders") or []
        if holders and isinstance(holders[0], dict):
            tick = str(holders[0].get("ticker") or "").upper().strip()
    if tick:
        return f"{company} ({tick})"
    return company


def format_card_lines(card: dict[str, Any]) -> list[str]:
    uses = "; ".join(str(u) for u in (card.get("possible_uses") or [])[:3])
    impacts = card.get("market_impacts") or []
    impact_bits = []
    for row in impacts[:2]:
        if not isinstance(row, dict):
            continue
        tickers = ",".join(row.get("tickers") or [])
        impact_bits.append(f"{row.get('sector', '')} [{row.get('bias', '')}] {tickers}")
    lines = [
        f"Held by: {format_holder_label(card)}",
        f"Industry: {card.get('industry') or ''}",
        f"Intended: {card.get('intended_use') or ''}",
    ]
    if uses:
        lines.append(f"Possible uses: {uses}")
    terms = card.get("impact_terms") or []
    windows = card.get("impact_windows") or {}
    if terms:
        bits = []
        for t in terms:
            hs = "/".join((windows.get(t) or IMPACT_WINDOWS.get(t) or ()))
            bits.append(f"{t} ({hs})" if hs else str(t))
        lines.append("Impact window: " + " + ".join(bits) + " — pipeline prices this, not this agent")
    if impact_bits:
        lines.append("Sector overlay: " + " | ".join(impact_bits))
    return lines
