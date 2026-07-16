#!/usr/bin/env python3
"""Build desktop PDF: agent decision system overview + every agent rulebook."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path.home() / "Desktop" / "ETrade_Trader_Agent_Decision_Guide.pdf"


def styles():
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle(
            "T",
            parent=base["Title"],
            fontSize=20,
            leading=24,
            spaceAfter=8,
            textColor=colors.HexColor("#0f172a"),
        ),
        "subtitle": ParagraphStyle(
            "ST",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#475569"),
            alignment=TA_CENTER,
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontSize=14,
            leading=18,
            spaceBefore=14,
            spaceAfter=8,
            textColor=colors.HexColor("#0f172a"),
            borderPadding=3,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontSize=12,
            leading=15,
            spaceBefore=10,
            spaceAfter=5,
            textColor=colors.HexColor("#1e3a5f"),
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontSize=10.5,
            leading=13,
            spaceBefore=7,
            spaceAfter=3,
            textColor=colors.HexColor("#334155"),
        ),
        "body": ParagraphStyle(
            "B",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            alignment=TA_JUSTIFY,
            spaceAfter=5,
            textColor=colors.HexColor("#1e293b"),
        ),
        "bullet": ParagraphStyle(
            "Bu",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            leftIndent=10,
            spaceAfter=2,
            textColor=colors.HexColor("#1e293b"),
        ),
        "mono": ParagraphStyle(
            "M",
            parent=base["Code"],
            fontSize=7.5,
            leading=10,
            fontName="Courier",
            backColor=colors.HexColor("#f1f5f9"),
            borderPadding=4,
            spaceAfter=6,
            spaceBefore=2,
        ),
        "note": ParagraphStyle(
            "N",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=6,
        ),
        "toc": ParagraphStyle(
            "TOC",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            leftIndent=8,
            spaceAfter=2,
        ),
        "agent_title": ParagraphStyle(
            "AT",
            parent=base["Heading1"],
            fontSize=13,
            leading=16,
            spaceBefore=4,
            spaceAfter=6,
            textColor=colors.HexColor("#0b3d5c"),
            backColor=colors.HexColor("#e8f1f8"),
            borderPadding=6,
        ),
    }
    return s


def hr():
    return HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=8)


def bullets(items, style):
    flow = []
    for it in items:
        flow.append(Paragraph(f"• {it}", style))
    return flow


def rule_table(rows, col_widths=None):
    """rows: list of list of strings; first row header."""
    data = [[Paragraph(str(c), ParagraphStyle("td", fontSize=7.5, leading=9.5)) for c in r] for r in rows]
    t = Table(data, colWidths=col_widths or [1.5 * inch, 5.5 * inch], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.HexColor("#eef2ff")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def agent_header(story, s, name, agent_id, persona, output, data_src):
    story.append(Paragraph(name, s["agent_title"]))
    story.append(
        Paragraph(
            f"<b>ID:</b> {agent_id} &nbsp;|&nbsp; <b>Persona:</b> {persona} &nbsp;|&nbsp; "
            f"<b>Output:</b> <font face='Courier'>{output}</font><br/>"
            f"<b>Data:</b> {data_src}",
            s["note"],
        )
    )


def build():
    s = styles()
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="E*TRADE Trader — Agent Decision Guide",
        author="Finance / ETrade Trader",
    )
    story = []

    # ── Cover ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.2 * inch))
    story.append(Paragraph("E*TRADE Trader", s["title"]))
    story.append(Paragraph("Agent Decision System — Complete Rulebook", s["title"]))
    story.append(
        Paragraph(
            f"How research agents form opinions, fuse into forecasts, and drive trades<br/>"
            f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}<br/>"
            f"Source: C:\\Users\\Box One\\Finance",
            s["subtitle"],
        )
    )
    story.append(hr())
    story.append(
        Paragraph(
            "This document has two parts: (1) the system overview of how agent decisions "
            "are made and fused into trading, and (2) a branch-by-branch rulebook for every "
            "platform agent including exact thresholds, biases, tickers, and fallbacks.",
            s["body"],
        )
    )
    story.append(PageBreak())

    # ── TOC ────────────────────────────────────────────────────────────
    story.append(Paragraph("Contents", s["h1"]))
    toc = [
        "Part I — System overview: how agent decisions are made",
        "Part II — Every agent decision rulebook",
        "    Markets & Finance: markets, finance, financial-data, datascience, sales-analytics, order-execution",
        "    Probability & Stats: theoretical, empirical, combined-conditional, research-statistics",
        "    Intelligence: events, geopolitics, patents",
        "    Energy & Infrastructure: electricity, grid, meteorology, transportation, logistics",
        "    Data Platform: data-steward, records-management",
        "    Ensemble: market-predictor",
        "Part III — Shared post-processing (personality, learning, disagreement, fusion)",
    ]
    for line in toc:
        story.append(Paragraph(line, s["toc"]))
    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════
    # PART I
    # ═══════════════════════════════════════════════════════════════════
    story.append(Paragraph("Part I — How Agent Decisions Are Made", s["h1"]))
    story.append(hr())

    story.append(Paragraph("1. What an agent decision is", s["h2"]))
    story.append(
        Paragraph(
            "Agents do <b>not</b> call a free-form LLM to pick stocks. Each agent is a "
            "<b>rule-based specialist</b>: pull public (or E*TRADE) data → compute metrics → "
            "apply thresholds → emit a structured JSON report. Those reports are later "
            "<b>fused</b>, <b>accuracy-weighted</b>, and <b>gated</b> before any order is placed.",
            s["body"],
        )
    )
    story.append(
        Paragraph(
            "An atomic decision is a <b>market_signal</b>:",
            s["body"],
        )
    )
    story.append(
        Paragraph(
            "sector, tickers[], bias (BULLISH | NEUTRAL | BEARISH), reason, "
            "confidence?, evidence?",
            s["mono"],
        )
    )
    story.append(
        Paragraph(
            "Bias map used almost everywhere: BULLISH = +1.0, NEUTRAL ≈ 0 / +0.15, BEARISH = −1.0. "
            "In fusion, signal strength is often: <font face='Courier'>delta = bias_score × 0.35 × "
            "fusion_weight × disagreement_mult × …</font>",
            s["body"],
        )
    )

    story.append(Paragraph("2. Shared brain — BaseExpert", s["h2"]))
    for item in [
        "<b>Temperature</b> — resolved from learning posture + accuracy; pipeline typically clamps to 2–4.",
        "<b>Pipeline memory</b> — trust_symbols (conf × ~1.08), avoid_symbols (conf × ~0.75 / skip), lessons, preferred horizon.",
        "<b>Domain lane</b> — domain_allows_symbol keeps specialists in their sector/theme universe.",
        "<b>Watchlist steering</b> — merges static list + live quotes + persistent bulls + trust − avoid.",
        "<b>Confidence adjustment</b> — final_conf = base × memory_factor × disagreement_confidence_factor(peers).",
        "<b>Personality metadata</b> — traits (risk appetite, conviction, patience, contrarian, defensive, vol tolerance).",
    ]:
        story.append(Paragraph(f"• {item}", s["bullet"]))

    story.append(Paragraph("3. Pipeline order each cycle", s["h2"]))
    story.append(
        Paragraph(
            "1) Start pipeline memory + cycle id<br/>"
            "2) Proactive E*TRADE quote enhancement<br/>"
            "3) Run each catalog agent → write output/&lt;file&gt;.json → personality + learning patch → same-cycle memory<br/>"
            "4) E*TRADE enhancement pass for symbols agents requested<br/>"
            "5) Optional accuracy backtest / calibration<br/>"
            "6) Market Predictor fuses all reports → market_predictions.json<br/>"
            "7) portfolio_generator + strategy_engine → swing/day orders (gates, guards, execute)",
            s["body"],
        )
    )

    story.append(Paragraph("4. From agent vote → trade (recap)", s["h2"]))
    story.append(
        Paragraph(
            "<b>Score</b> every ticker from signals + predictor rows (accuracy/domain/horizon weighted) → "
            "<b>portfolio</b> top N weights (3–15% caps) → <b>drift rebalance</b> vs live positions → "
            "<b>trading gate</b> (sample/accuracy floors + multi-cluster agreement) → "
            "<b>trade guards</b> (buying power, PDT) → market/limit selector → preview/place. "
            "Day trading uses a separate loop on 24h predictor / portfolio candidates with TP/SL/flatten rules.",
            s["body"],
        )
    )

    story.append(Paragraph("5. Decision modes", s["h2"]))
    story.append(
        rule_table(
            [
                ["Setting", "Effect"],
                ["agent_controlled=true", "Pick what agents pick; growth ordering (default)"],
                ["agent_controlled=false", "Profit-optimizer multi-horizon weights; regime sleeves"],
                ["trading_gate.*", "Accuracy floors, cluster agreement vetoes on BUYs"],
                ["dry_run / sandbox", "Simulate or paper API — no live money"],
                ["paused / Stop all", "Halt pipeline/plan/execute loops"],
            ],
            [1.8 * inch, 5.2 * inch],
        )
    )
    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════
    # PART II — EVERY AGENT
    # ═══════════════════════════════════════════════════════════════════
    story.append(Paragraph("Part II — Every Agent Decision Rulebook", s["h1"]))
    story.append(
        Paragraph(
            "For each agent: data sources, analyze() flow, exact market_signals branches "
            "(thresholds → bias → tickers), special outputs, labels, and fallbacks. "
            "Confidence is almost always passed through adjust_signal_confidence after base computation.",
            s["body"],
        )
    )
    story.append(hr())

    # ── MARKETS ────────────────────────────────────────────────────────
    agent_header(
        story, s,
        "1. Market Analyst Expert (markets)",
        "markets",
        "The Momentum Hawk",
        "markets.json",
        "Yahoo Finance charts, trending, day_gainers / day_losers screeners",
    )
    story.append(Paragraph("Analyze flow", s["h3"]))
    for item in [
        "Fetch quotes for US indices, risk symbols, sector ETFs, growth/value proxies, commodities.",
        "Fetch trending symbols + top gainers/losers.",
        "Compute breadth (avg index day %), risk_on (blend of −VIX day%, Nasdaq, XLK), momentum, dispersion.",
        "Build assessment text + market_signals + recommendations.",
    ]:
        story.append(Paragraph(f"• {item}", s["bullet"]))
    story.append(Paragraph("Key metrics", s["h3"]))
    story.append(
        Paragraph(
            "risk_on: _norm_score of mean(−VIX%, Nasdaq%, XLK%), scale 5.0 → label Risk-On if ≥0.60, "
            "Risk-Off if ≤0.40, else Neutral. breadth_score / momentum_score / dispersion_score similarly normalized.",
            s["body"],
        )
    )
    story.append(Paragraph("market_signals branches", s["h3"]))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers / Notes"],
                ["|breadth| ≥ 0.2%", "BULLISH if breadth>0.3; BEARISH if <−0.3; else NEUTRAL → SPY,QQQ,IWM"],
                ["risk_on ≥ 0.60", "BULLISH Growth/Tech → QQQ,XLK,NVDA,MSFT"],
                ["risk_on ≤ 0.40", "BULLISH Defensives → XLU,XLP,GLD,TLT"],
                ["sector leader day% > 0.4", "BULLISH if >0.5 else NEUTRAL → that sector ETF"],
                ["sector laggard day% < −0.5", "BEARISH → that sector ETF"],
                ["|XLE day%| > 0.75", "BULLISH if XLE>0 else BEARISH → XLE,USO,XOM"],
                ["top gainer day% ≥ 2.0", "BULLISH Top Movers → first 5 gainer symbols"],
                ["no signals", "NEUTRAL Broad Market → SPY conf~0.42"],
            ],
            [2.2 * inch, 4.8 * inch],
        )
    )
    story.append(Paragraph("Recs: risk_on≥0.65 favor growth/momentum; ≤0.35 raise cash/defensives/hedges.", s["note"]))
    story.append(Spacer(1, 6))

    # ── FINANCE ────────────────────────────────────────────────────────
    agent_header(
        story, s,
        "2. Google Finance Beta Analyst (finance)",
        "finance",
        "The Opportunity Scout",
        "finance.json",
        "Yahoo charts/screeners mapped as Google Finance Beta views (sectors, indices, futures, crypto, movers)",
    )
    story.append(Paragraph("Trading opportunities (per symbol)", s["h3"]))
    story.append(
        rule_table(
            [
                ["Pattern", "Strategy / Score"],
                ["day>1.5% AND week>0", "momentum_continuation; score = min(1, 0.55+day×0.04+week×0.02)"],
                ["day<−2% AND z_5d<−1", "mean_reversion; score = min(1, 0.50+|day|×0.03)"],
                ["day>2% AND week<0", "breakout_reversal; score = min(1, 0.45+day×0.03)"],
                ["|day|>0.8% else", "swing_trade; score = 0.40+|day|×0.02"],
                ["otherwise", "skip — not an opportunity"],
            ],
            [2.3 * inch, 4.7 * inch],
        )
    )
    story.append(Paragraph("Top 10 opportunities by opportunity_score. Strategy tags later steer market vs limit orders.", s["note"]))
    story.append(Paragraph("market_signals branches", s["h3"]))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["leading sector day% > 0.35", "BULLISH if >0.5 else NEUTRAL → mapped SPDR ETF"],
                ["lagging sector day% < −0.6", "BEARISH → mapped ETF"],
                ["Nasdaq day% < −0.75", "BEARISH tech → QQQ,XLK,NVDA,MSFT"],
                ["risk_reward ≥ 0.62 and has opps", "BULLISH → top 5 opportunity symbols"],
                ["no signals", "NEUTRAL → SPY,DIA,IWM"],
            ],
            [2.5 * inch, 4.5 * inch],
        )
    )
    story.append(Paragraph(
        "Tape label Opportunity-Rich if opportunity_score≥0.65, Selective ≥0.45, else Quiet. "
        "opportunity_score blends momentum×0.35 + dispersion×0.25 + top_opp×0.40.",
        s["body"],
    ))
    story.append(Spacer(1, 6))

    # ── FINANCIAL DATA ─────────────────────────────────────────────────
    agent_header(
        story, s,
        "3. Yahoo Finance Statistical Analyst (financial-data)",
        "financial-data",
        "The Statistician",
        "financial_data.json",
        "Yahoo Finance sector returns, movers, SPY history for z/vol/trend",
    )
    story.append(Paragraph("Analyze: cross-section mean/median/σ/skew/kurtosis of sector returns; breadth A/D; sector z-scores; "
                           "correlation matrix; SPY beta/vol regime; mover outliers (|z|≥1.8); SPY linear trend.", s["body"]))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["statistical_score ≥0.55 or ≤0.45", "BULLISH if ≥0.6; BEARISH if ≤0.4; else NEUTRAL → SPY,QQQ,IWM"],
                ["sector z ≥ +1.6", "BULLISH → that sector ETF"],
                ["sector z ≤ −1.6", "BEARISH → that sector ETF"],
                ["mover |z| ≥ 1.8", "BULLISH if day%>0 else BEARISH → mover symbol"],
                ["VIX 20d z ≥ 1.4", "BULLISH hedges → VIXY/defensives style (GLD path in code)"],
                ["no signals", "NEUTRAL SPY conf~0.42"],
            ],
            [2.4 * inch, 4.6 * inch],
        )
    )
    story.append(Paragraph(
        "Assessment: bullish regime if mean_return>0.5 and breadth_pct_positive≥60; bearish if mean&lt;−0.5 and breadth≤40. "
        "A/D ≥2 broad advance; ≤0.5 broad decline.",
        s["note"],
    ))
    story.append(Spacer(1, 6))

    # ── DATASCIENCE ────────────────────────────────────────────────────
    agent_header(
        story, s,
        "4. Data Science Expert (datascience)",
        "datascience",
        "The Quant",
        "datascience.json",
        "Yahoo 6mo daily closes — SPY,QQQ,IWM,XLK,XLE,XLF,XLU,GLD,TLT,HYG",
    )
    story.append(Paragraph(
        "Per ticker: 1d/5d/20d returns, 20d ann vol, 20d z-score, empirical P(up), "
        "Monte Carlo 5d (5000 paths) → P(up) + median return, momentum_score = clamp(0.5 + (r20/vol)×0.15), "
        "mean_reversion_score = |z|/3.",
        s["body"],
    ))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["SPY mom≥0.65 AND mc_prob_up≥0.55", "BULLISH SPY/QQQ"],
                ["SPY mom≤0.4 AND stress≥0.45", "BULLISH defensives GLD/TLT (risk-off style)"],
                ["z≤−1.4 AND mc_prob_up≥0.52", "BULLISH oversold bounce → that ticker"],
                ["z≥1.8 overbought", "BEARISH → that ticker"],
                ["factor leader mom≥0.62, r20≥2, not SPY", "BULLISH → leader symbol"],
                ["HYG 20d ret < −2%", "BEARISH credit stress → HYG,SPY"],
                ["no signals", "NEUTRAL SPY"],
            ],
            [2.8 * inch, 4.2 * inch],
        )
    )
    story.append(Paragraph(
        "Regime: trending bullish if SPY r20>2 and mom≥0.6; bearish if r20&lt;−2 and mom≤0.4. "
        "Opportunity score from count of oversold+MC and high-momentum names. "
        "Label Stressed/Cautious/Constructive from stress vs opportunity.",
        s["note"],
    ))
    story.append(PageBreak())

    # ── SALES ──────────────────────────────────────────────────────────
    agent_header(
        story, s,
        "5. Sales Analytics BI Expert (sales-analytics)",
        "sales-analytics",
        "The Retail Reader",
        "sales_analytics.json",
        "Yahoo retail proxies + XLY/XLP sector context",
    )
    story.append(Paragraph(
        "Momentum per retailer from 5d/20d returns; category aggregates; consumer_strength from "
        "0.4×momentum_index + breadth terms; strength Strong if ≥0.62.",
        s["body"],
    ))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["strength≥0.62 AND breadth≥55%", "BULLISH → SPY,XLY,IWM"],
                ["strength≤0.38 AND breadth≤45%", "BEARISH cyclicals SPY,XLY,IWM; BULLISH staples/def if strength≤0.32 → XLP,TLT"],
                ["leading category mom≥0.58", "BULLISH XLY,SPY"],
                ["discretionary premium > +0.8%", "BULLISH XLY,SPY"],
                ["staples premium (disc < −0.8%)", "staples rotation XLP,SPY"],
                ["e-commerce weak", "additional soft-demand notes / NEUTRAL-BEARISH consumer tilt"],
            ],
            [2.6 * inch, 4.4 * inch],
        )
    )
    story.append(Spacer(1, 6))

    # ── ORDER EXECUTION ────────────────────────────────────────────────
    agent_header(
        story, s,
        "6. Order Execution Expert (order-execution)",
        "order-execution",
        "The Execution Purist",
        "order_execution.json",
        "Yahoo 3mo OHLCV for SPY,AAPL,MSFT,QQQ,IWM,GME,COIN,PLTR + VIX",
    )
    story.append(Paragraph(
        "This agent does <b>not</b> emit classic BULLISH/BEARISH portfolio votes. Signals are microstructure tags "
        "that guide how to route orders (used by order_type_selector / operator judgment).",
        s["body"],
    ))
    story.append(
        rule_table(
            [
                ["Rule", "Decision"],
                ["avg $ volume ≥ $200M", "Liquidity tier Deep"],
                ["≥ $25M and < $200M", "Moderate"],
                ["< $25M", "Thin"],
                ["max overnight gap ≥ 3%", "gap risk → prefer stop-limit over stop-market"],
                ["Deep + no gap", "Market order acceptable"],
                ["Thin book", "Limit order recommended"],
                ["Moderate", "Marketable limit recommended"],
                ["VIX ≥ 25", "High-vol regime — favor limits/stop-limits"],
                ["VIX ≥ 18", "Moderate vol"],
                ["VIX < 18", "Low vol — market OK in deep names"],
            ],
            [2.2 * inch, 4.8 * inch],
        )
    )
    story.append(Paragraph(
        "Signals: bias=execution-risk (thin names), gap-risk (gap-prone), execution-safe (deep). "
        "Fees assumed: taker 3 bps, maker 0.5 bps.",
        s["note"],
    ))
    story.append(Spacer(1, 6))

    # ── THEORETICAL PROB ───────────────────────────────────────────────
    agent_header(
        story, s,
        "7. Theoretical Probability Expert",
        "theoretical-probability",
        "The Theorist",
        "theoretical_probability.json (+ probability_models.json)",
        "Yahoo history — Markov, Bayesian, conditional probs, streak models, GBM barriers, Kelly EV",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["posterior bull & post_p≥0.58", "BULLISH SPY"],
                ["posterior bear & post_p≥0.58", "BEARISH SPY"],
                ["Markov one-step bull ≥0.52", "BULLISH SPY"],
                ["Markov one-step bear ≥0.52", "BEARISH SPY"],
                ["conditional P ≥0.68", "BULLISH related symbols"],
                ["barrier P ≥0.30 (drawdown)", "BEARISH that symbol"],
                ["streak anomaly long up ≥4 & theory<5%", "unusual streak notes"],
            ],
            [2.6 * inch, 4.4 * inch],
        )
    )
    story.append(Paragraph(
        "Conditional: P≥0.65 strong / ≤0.35 weak. Barrier: ≥0.35 elevated drawdown risk. "
        "Label conviction from model agreement; bull if dom=bull and conviction≥0.55.",
        s["note"],
    ))
    story.append(Spacer(1, 6))

    # ── EMPIRICAL PROB ─────────────────────────────────────────────────
    agent_header(
        story, s,
        "8. Empirical Probability Expert",
        "empirical-probability",
        "The Experimentalist",
        "empirical_probability.json",
        "Yahoo history — rolling win rates, Wilson CIs, return bins, after-up/after-down trials",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Notes"],
                ["Wilson edge valid on SPY (n≥ min samples, CI clears 50%)", "bias_from_edge P(up): bullish≥0.54, bearish≤0.46 → SPY"],
                ["stable experiment win rate high", "BULLISH supporting signal"],
                ["P(up|2 down days) ≥0.58 & sample OK", "BULLISH mean-reversion"],
                ["20d win rate < 120d − 10pp", "BEARISH short-term deterioration"],
            ],
            [3.0 * inch, 4.0 * inch],
        )
    )
    story.append(Paragraph(
        "wilson_edge_valid requires samples≥30 (caller often min_samples=40), |edge|≥5pp, and CI on correct side of 50%. "
        "Evidence score blends SPY empirical P(up) and experiment stability.",
        s["note"],
    ))
    story.append(Spacer(1, 6))

    # ── COMBINED CONDITIONAL ───────────────────────────────────────────
    agent_header(
        story, s,
        "9. Combined & Conditional Probability Expert",
        "combined-conditional",
        "The Conditional Thinker",
        "combined_conditional.json",
        "Yahoo multi-symbol history — joint/conditional probs, independence ratios",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias"],
                ["top joint_prob ≥0.35 and event_a is 'up'", "BULLISH joint setup symbols"],
                ["conditional_prob ≥0.68 or ≤0.32", "BULLISH if ≥0.5 else BEARISH"],
                ["multi-cond P ≥0.65", "BULLISH"],
                ["independence_ratio ≥1.4", "BULLISH (dependence structure edge)"],
                ["combined_prob ≥0.55", "BULLISH"],
                ["else", "NEUTRAL baseline"],
            ],
            [3.2 * inch, 3.8 * inch],
        )
    )
    story.append(Paragraph(
        "Requires n≥30 for most estimates; conditional cells need min index counts (often ≥5–8). "
        "Joint P≥0.35 'elevated joint'; ≤0.10 'rare'. Cond P≥0.70 strong / ≤0.30 weak.",
        s["note"],
    ))
    story.append(PageBreak())

    # ── RESEARCH STATS ─────────────────────────────────────────────────
    agent_header(
        story, s,
        "10. Research Statistics Expert",
        "research-statistics",
        "The Research Scientist",
        "research_statistics.json",
        "Yahoo — hypothesis tests, effect sizes, variance tests, practical findings",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias"],
                ["significant SPY mean test (p typically <0.05 path)", "BULLISH if t>0 else BEARISH if t<0"],
                ["significant finding text implies outperform/momentum", "BULLISH"],
                ["underperform / negative / fat tail language", "BEARISH"],
                ["positive factor / leadership findings", "BULLISH related ETFs"],
                ["no strong findings", "NEUTRAL SPY"],
            ],
            [3.2 * inch, 3.8 * inch],
        )
    )
    story.append(Paragraph(
        "significance_score from count of significant tests (sig_count≥4 strong, ≥2 moderate). "
        "Label constructive if significance_score≥0.55 and sig_count≥3.",
        s["note"],
    ))
    story.append(Spacer(1, 6))

    # ── EVENTS ─────────────────────────────────────────────────────────
    agent_header(
        story, s,
        "11. World Events Tracker (events)",
        "events",
        "The Headline Watch",
        "world_events.json (+ world_events_tracker.json)",
        "BBC World / NPR RSS — classify category, region, impact; recency decay half-life ~48h",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["stress_score ≥1.2 OR ≥1 critical event", "BULLISH if stress≥1.8 else NEUTRAL → hedges GLD/TLT/VIXY-style set"],
                ["geo_score ≥0.85", "BULLISH if ≥1.2 else NEUTRAL defense/safe-haven basket"],
                ["energy_score ≥0.65", "BULLISH if ≥1.0 else NEUTRAL energy"],
                ["no stress", "NEUTRAL SPY"],
            ],
            [2.8 * inch, 4.2 * inch],
        )
    )
    story.append(Paragraph(
        "weighted_event_score: critical=1.0, high=0.72, medium=0.4, low=0.2 × exp decay by age.",
        s["note"],
    ))
    story.append(Spacer(1, 6))

    # ── GEOPOLITICS ────────────────────────────────────────────────────
    agent_header(
        story, s,
        "12. Geopolitics Expert",
        "geopolitics",
        "The Risk Sentinel",
        "geopolitics.json",
        "BBC/NPR (+ optional GDELT) — theater risk scores Ukraine, ME, China, energy, sanctions",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["global_risk ≥0.48", "GLD,IAU,GDX BULLISH if ≥0.62 else NEUTRAL"],
                ["escalation ≥0.5 (with global risk)", "TLT,IEF,SHY BULLISH if esc≥0.58 else NEUTRAL"],
                ["Ukraine risk≥0.45 & articles≥2", "Defense LMT,RTX,NOC,GD BULLISH if ≥0.62; FEZ/EWG/VGK BEARISH if ≥0.65"],
                ["ME or energy risk ≥0.40", "USO,XLE,XOM,CVX BULLISH if ≥0.60 else NEUTRAL"],
                ["China/Taiwan risk ≥0.40", "SOXX,TSM,NVDA,FXI BEARISH if ≥0.60 else NEUTRAL"],
                ["sanctions risk ≥0.35", "EEM,INDA,KWEB BEARISH if ≥0.55 else NEUTRAL"],
                ["no signals", "NEUTRAL SPY,GLD"],
            ],
            [2.6 * inch, 4.4 * inch],
        )
    )
    story.append(Paragraph(
        "Global risk labels: Critical≥0.75, Elevated≥0.55, Moderate≥0.35, else Low. "
        "Escalation trend from avg theater escalation thresholds 0.55/0.35.",
        s["note"],
    ))
    story.append(Spacer(1, 6))

    # ── PATENTS ────────────────────────────────────────────────────────
    agent_header(
        story, s,
        "13. Patent Landscape Analyst",
        "patents",
        "The Innovation Scout",
        "patents.json",
        "OpenAlex, IPWatchdog RSS, USPTO feeds + resource catalog health",
    )
    story.append(Paragraph(
        "innovation_score = min(100, hot_sectors×14 + online×2 + total_filings×1.5) where hot_sector has count≥3. "
        "High velocity ≥70, Moderate ≥45, else Quiet.",
        s["body"],
    ))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["score ≥70", "BULLISH QQQ,SPY,XLK"],
                ["top sectors count≥2 (not general)", "BULLISH if count≥4 else NEUTRAL — sector-mapped ETFs"],
                ["high_impact_count ≥2 and score<70", "NEUTRAL QQQ,SPY catalyst watch"],
                ["score <45 and no other signals", "NEUTRAL SPY quiet landscape"],
            ],
            [2.6 * inch, 4.4 * inch],
        )
    )
    story.append(PageBreak())

    # ── ELECTRICITY ────────────────────────────────────────────────────
    agent_header(
        story, s,
        "14. EIA Grid Monitor Analyst (electricity)",
        "electricity",
        "The Grid Steward",
        "electricity.json",
        "EIA Open Data v2 region-data + fuel-type-data (US48)",
    )
    story.append(Paragraph(
        "Stress from demand–generation gap, gas%, coal%, renewable shortfall: "
        "Elevated ≥60, Moderate ≥35, else Normal. Signals via power_grid_market_impact_signals.",
        s["body"],
    ))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["stress≥65 OR avg LMP≥$55", "BEARISH SPY,XLI,IWM; hedges TLT,GLD BULLISH if stress≥70"],
                ["stress<40 AND LMP≤$22", "BULLISH SPY,IWM low power cost"],
                ["renewable≥38% AND stress<50", "BULLISH QQQ,SPY if renewable≥42 else NEUTRAL"],
                ["gas≥45% (+ weather energy if present)", "BEARISH SPY,IWM if gas≥50; BULLISH UNG,XLE transmission"],
                ["peak_load ≥75,000 MW (and not high stress)", "BULLISH SPY,XLI strong economic load"],
                ["40≤stress<65 no other", "NEUTRAL SPY"],
                ["else", "NEUTRAL SPY baseline"],
            ],
            [2.8 * inch, 4.2 * inch],
        )
    )
    story.append(Spacer(1, 6))

    # ── GRID ───────────────────────────────────────────────────────────
    agent_header(
        story, s,
        "15. Electrical Grid Analyst (grid)",
        "grid",
        "The Cautious Engineer",
        "grid.json",
        "Grid Status Live, ERCOT/CAISO public, EIA RTO, optional Grid Status LMP API",
    )
    story.append(Paragraph(
        "Stress = min(100, gas_avg×0.6 + LMP stress + renewable deficit terms). "
        "Elevated ≥65, Moderate ≥40. Uses same power_grid_market_impact_signals helper as electricity "
        "with ERCOT gas%, avg hub LMP, peak load, weather_energy cross-link.",
        s["body"],
    ))
    story.append(Paragraph("Same market signal threshold table as electricity (shared helper).", s["note"]))
    story.append(Spacer(1, 6))

    # ── METEOROLOGY ────────────────────────────────────────────────────
    agent_header(
        story, s,
        "16. Meteorology Expert",
        "meteorology",
        "The Weather Watch",
        "meteorology.json",
        "weather.gov / NWS API alerts + hub forecasts",
    )
    story.append(Paragraph(
        "Disruption labels: Critical≥0.75, Elevated≥0.55, Moderate≥0.35. "
        "Heat stress steps at peaks 105/95/85°F; flood/cold/severe from alert counts.",
        s["body"],
    ))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["disruption ≥0.55", "BEARISH SPY,IWM,XLI if critical; BULLISH GLD,TLT,XLU if critical"],
                ["energy demand (energy≥0.55 or heat/cold)", "BEARISH SPY,IWM if energy≥0.72 or extreme heat/cold; BULLISH UNG,XLE,USO if energy≥0.72"],
                ["severe ≥0.35", "BEARISH SPY,XLI if severe≥0.5 else NEUTRAL"],
                ["tropical / ag drought-flood language", "additional ag/energy transmission signals"],
            ],
            [2.6 * inch, 4.4 * inch],
        )
    )
    story.append(Spacer(1, 6))

    # ── TRANSPORTATION ─────────────────────────────────────────────────
    agent_header(
        story, s,
        "17. Civil Transportation Analyst",
        "transportation",
        "The Infrastructure Analyst",
        "transportation.json",
        "data.transportation.gov — bridges, traffic, truck inspections, freight proxies",
    )
    story.append(Paragraph(
        "Infrastructure stress from unknown bridge design % + concentration + negative truck trends. "
        "Elevated ≥65, Moderate ≥40.",
        s["body"],
    ))
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["truck volume avg ≥ +3%", "BULLISH SPY,XLI,IWM freight expansion"],
                ["truck avg ≤ −2%", "BEARISH SPY,XLI,IWM freight contraction"],
                ["infra stress ≥65", "defensive / cost-pressure industrials tilt (helper branches)"],
                ["truck >> passenger (+2pp)", "freight-led cyclical confirmation"],
                ["passenger >> truck", "commute/consumer activity tilt"],
            ],
            [2.4 * inch, 4.6 * inch],
        )
    )
    story.append(Spacer(1, 6))

    # ── LOGISTICS ──────────────────────────────────────────────────────
    agent_header(
        story, s,
        "18. Logistics Expert",
        "logistics",
        "The Freight Tracker",
        "logistics.json",
        "MarineTraffic AIS (optional key) + corridor congestion/density models",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["supply_chain stress ≥0.55", "BEARISH SPY,XLI,IWM if ≥0.75 else NEUTRAL; HYG,TLT credit watch"],
                ["freight momentum ≥0.58 (not critical)", "BULLISH SPY,XLI,EEM if freight≥0.70 else NEUTRAL"],
                ["US WC congestion ≥0.58 or retail delays", "BEARISH XLY,SPY if WC≥0.72 else NEUTRAL"],
                ["tanker active & freight≥0.5", "BULLISH USO,XLE if freight≥0.65 else NEUTRAL"],
                ["stress <0.35", "NEUTRAL SPY balanced"],
            ],
            [2.8 * inch, 4.2 * inch],
        )
    )
    story.append(Paragraph(
        "Stress labels Critical≥0.75, Elevated≥0.55, Moderate≥0.35. Corridor congestion/density thresholds ~0.55–0.75 in assessment.",
        s["note"],
    ))
    story.append(PageBreak())

    # ── DATA STEWARD ───────────────────────────────────────────────────
    agent_header(
        story, s,
        "19. Data Steward Expert",
        "data-steward",
        "The Steward",
        "data_steward.json",
        "Platform catalog, output/ artifact health, schema completeness, source uptime",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["stewardship score ≥0.65", "BULLISH SPY (platform healthy)"],
                ["score ≤0.40", "BEARISH SPY"],
                ["any offline source", "BEARISH GLD,TLT (fallback risk)"],
                ["stale artifact", "BEARISH VIXY (stale intel risk)"],
                ["fresh + completeness≥0.85", "BULLISH XLK,QQQ quality data ready"],
            ],
            [2.4 * inch, 4.6 * inch],
        )
    )
    story.append(Paragraph(
        "Does not pick stocks for alpha; signals data readiness that fusion may down-weight when unhealthy. "
        "Required keys: meta, market_signals, recommendations.",
        s["note"],
    ))
    story.append(Spacer(1, 6))

    # ── RECORDS ────────────────────────────────────────────────────────
    agent_header(
        story, s,
        "20. Records Management Expert",
        "records-management",
        "The Archivist",
        "records_management.json",
        "Archive inventory, retention, integrity, snapshot archiving",
    )
    story.append(
        rule_table(
            [
                ["Condition", "Bias / Tickers"],
                ["archive score ≥0.70", "BULLISH SPY"],
                ["score ≤0.45", "BEARISH SPY"],
                ["integrity failure", "BEARISH VIXY,GLD"],
                ["≥10 valid primary agent reports", "BULLISH XLK,QQQ archive ready"],
            ],
            [2.6 * inch, 4.4 * inch],
        )
    )
    story.append(Spacer(1, 6))

    # ── MARKET PREDICTOR ───────────────────────────────────────────────
    agent_header(
        story, s,
        "21. Market Predictor (ensemble meta-agent)",
        "market-predictor",
        "The Ensemble Conductor",
        "market_predictions.json",
        "All other agents' JSON reports + E*TRADE enhanced quotes + history",
    )
    story.append(Paragraph("Analyze / fuse flow", s["h3"]))
    for item in [
        "Load every active agent report from platform catalog.",
        "For each market_signal: delta = bias_score×0.35; weight = fusion_weight(... for_trading=True); apply disagreement_mult; add to score and by_cluster.",
        "Extra bumps: finance opportunities (score×0.5 capped), datascience top_picks/factor_leaders, sales retail_leaders, markets risk-on/off ETF bumps, history persistent bulls, live E*TRADE quote presence (+0.15).",
        "apply_cluster_caps so one theme cannot dominate a ticker.",
        "Rank by score; take top 25 positives (pad with negatives if <8 movers).",
        "For each horizon in {1m,1h,24h,1wk,1mo,1yr}: re-rank with horizon-adjusted fusion weights; direction up if score>0.08, down if <−0.08, else flat; predicted_return = f(|score|)×horizon_scale; confidence from base conf + |score|.",
        "Write predictions[horizon][] ranked rows with sources and rationale.",
    ]:
        story.append(Paragraph(f"• {item}", s["bullet"]))
    story.append(Paragraph("Horizon return scales", s["h3"]))
    story.append(
        rule_table(
            [
                ["Horizon", "Return scale"],
                ["1m", "0.015"],
                ["1h", "0.08"],
                ["24h", "0.35"],
                ["1wk", "0.55"],
                ["1mo", "1.0"],
                ["1yr", "2.5"],
            ],
            [1.5 * inch, 5.5 * inch],
        )
    )
    story.append(Paragraph(
        "fusion_weight multiplies: domain, trading eligibility (accuracy samples/floor), accuracy history, "
        "horizon accuracy, regime accuracy, Brier calibration, historical simulation blend, account-balance penalty, "
        "personality×regime, learning fusion_multiplier, horizon match. Weight clamped ~[0, 1.5]. "
        "Zero weight ⇒ agent vote dropped.",
        s["body"],
    ))
    story.append(Paragraph(
        "Example JSON prediction row: rank, symbol, predicted_direction, predicted_return_pct, confidence, "
        "composite_score, sources[], rationale, price_at_prediction?, preferred_horizon.",
        s["mono"],
    ))
    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════
    # PART III
    # ═══════════════════════════════════════════════════════════════════
    story.append(Paragraph("Part III — Shared Post-Processing & Fusion", s["h1"]))
    story.append(hr())

    story.append(Paragraph("Personality patch (after every agent write)", s["h2"]))
    story.append(
        Paragraph(
            "Traits adjust bias (hawks strengthen bullish; sentinels strengthen defensive), "
            "scale confidence by conviction/temperature, scale opportunity_score by risk_appetite, "
            "and set preferred_horizon from patience (patient→1mo, mid→1wk, low→24h).",
            s["body"],
        )
    )

    story.append(Paragraph("Learning patch", s["h2"]))
    story.append(
        Paragraph(
            "Posture (cautious/learning/calibrated/confident), bias_drift, trust/avoid symbols, "
            "fusion_multiplier scale how much the agent is allowed to move the ensemble next cycle.",
            s["body"],
        )
    )

    story.append(Paragraph("Disagreement", s["h2"]))
    story.append(
        Paragraph(
            "Per symbol, sum bullish vs bearish confidences across agents. Contested if minority weight meaningful. "
            "Agents joining the minority get confidence crushed (~0.55×); majority slightly damped. "
            "Fusion multiplies contested scores by up to ~0.45 floor.",
            s["body"],
        )
    )

    story.append(Paragraph("Trading gate (portfolio / plan)", s["h2"]))
    story.append(
        rule_table(
            [
                ["Rule", "Default"],
                ["Min live samples", "25 (or 8 benchmark-only)"],
                ["Min accuracy", "~40% combined"],
                ["Min net score", "0.12"],
                ["Min agreeing clusters", "2 with contrib ≥0.08 each"],
                ["Fusion-backed exception", "Market-predictor eligible may pass cluster failure"],
                ["Failing BUY", "status=blocked — not sent"],
            ],
            [2.2 * inch, 4.8 * inch],
        )
    )

    story.append(Paragraph("Portfolio weight formula", s["h2"]))
    story.append(
        Paragraph(
            "weight ∝ max(0.01, score); clamp each weight to [3%, 15%]; renormalize to 100%. "
            "Default ~12 holdings (3–6 in small-account mode under ~$500 with affordable share preference).",
            s["body"],
        )
    )

    story.append(Paragraph("Mental model", s["h2"]))
    story.append(
        Paragraph(
            "Agents decide with heuristics and statistics → peers adjust confidence → "
            "Market Predictor accuracy-weights and ranks → portfolio + gates allocate capital → "
            "strategy engine / day trader propose orders → guards + dry-run/sandbox decide if money moves. "
            "<b>No single agent places a trade.</b>",
            s["body"],
        )
    )

    story.append(Spacer(1, 12))
    story.append(hr())
    story.append(
        Paragraph(
            "Code map: agents/base.py · agent_signal_logic.py · agents/*/expert.py · "
            "agents/market_predictor.py · agent_fusion.py · agent_disagreement.py · "
            "agent_personality.py · agent_learning.py · agent_temperature.py · "
            "agent_constraints.py · portfolio_generator.py · strategy_engine.py · "
            "trading_gate.py · day_trader.py · trade_guards.py",
            s["note"],
        )
    )
    story.append(
        Paragraph(
            f"Document saved to: {OUT}",
            s["note"],
        )
    )

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(0.65 * inch, 0.4 * inch, "E*TRADE Trader — Agent Decision Guide")
        canvas.drawRightString(letter[0] - 0.65 * inch, 0.4 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return OUT


if __name__ == "__main__":
    path = build()
    print(path)
    print("bytes", path.stat().st_size)
