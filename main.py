#!/usr/bin/env python3
"""Finance repo — run intelligence agents from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from agents.datascience import run_datascience_analysis
from agents.electricity import run_electricity_analysis
from agents.empirical_probability import run_empirical_probability_analysis
from agents.combined_conditional import run_combined_conditional_analysis
from agents.data_steward import run_data_steward_analysis
from agents.events import run_events_analysis
from agents.finance import run_finance_analysis
from agents.financial_data import run_financial_data_analysis
from agents.geopolitics import run_geopolitics_analysis
from agents.grid import run_grid_analysis
from agents.information_theory import run_information_theory_analysis
from agents.logistics import run_logistics_analysis
from agents.markets import run_markets_analysis
from agents.meteorology import run_meteorology_analysis
from agents.patents import run_patents_analysis
from agents.records_management import run_records_management_analysis
from agents.research_statistics import run_research_statistics_analysis
from agents.sales_analytics import run_sales_analytics_analysis
from agents.theoretical_probability import run_theoretical_probability_analysis
from agents.transportation import run_transportation_analysis


def _print_signals(signals: list[dict[str, Any]]) -> None:
    if not signals:
        return
    print("  Market signals:")
    for sig in signals:
        tickers = ", ".join(sig.get("tickers", []))
        print(f"    • {sig.get('sector')} [{sig.get('bias')}] — {tickers}")
        print(f"      {sig.get('reason')}")
    print()


def _print_recs(recs: list[str], limit: int = 10) -> None:
    if not recs:
        return
    print("  Recommendations:")
    for r in recs[:limit]:
        print(f"    • {r}")
    print()


def _print_meteorology(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('region_name', '')}")
    print("=" * 60)
    print(f"  {meta.get('national_headline', '')}")
    print()
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Disruption: {metrics.get('disruption_label')} ({metrics.get('disruption_score')})")
    print(f"  Heat: {metrics.get('heat_stress_score')}  |  Cold: {metrics.get('cold_stress_score')}")
    print(f"  Severe: {metrics.get('severe_weather_score')}  |  Flood: {metrics.get('flood_risk_score')}")
    print(f"  Energy demand: {metrics.get('energy_demand_score')}")
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_markets(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Regime: {metrics.get('trend_label')} (risk-on {metrics.get('risk_on_score')})")
    print(f"  Breadth: {metrics.get('breadth_score')}  |  Momentum: {metrics.get('momentum_score')}")
    print()
    for q in data.get("indices", [])[:5]:
        wk = f" / 1w {q.get('week_chg_pct'):+.2f}%" if q.get("week_chg_pct") is not None else ""
        print(f"  • {q.get('symbol')}: {q.get('day_chg_pct'):+.2f}%{wk}")
    print()
    print("  Sector leaders:")
    for s in data.get("sectors", [])[:5]:
        print(f"    #{s.get('rank')} {s.get('sector')} ({s.get('etf')}): {s.get('day_chg_pct'):+.2f}%")
    print()
    gainers = data.get("top_gainers", [])[:5]
    if gainers:
        print("  Top gainers: " + ", ".join(
            f"{g.get('symbol')} {g.get('day_chg_pct'):+.2f}%" for g in gainers
        ))
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_financial_data(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    cs = data.get("cross_section", {})
    assessment = data.get("statistical_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — Yahoo Finance")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Regime: {metrics.get('regime_label')} "
        f"(statistical score {metrics.get('statistical_score')})"
    )
    print(
        f"  Breadth: {metrics.get('breadth_score')} | "
        f"Volatility: {metrics.get('volatility_score')}"
    )
    print(
        f"  Cross-section: μ {cs.get('mean_return_pct'):+.2f}% | "
        f"σ {cs.get('stdev_pct'):.2f}% | "
        f"skew {cs.get('skewness'):+.2f} | "
        f"A/D {cs.get('advance_decline_ratio'):.1f}x"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Sector statistics (cross-section z):")
    for s in data.get("sectors", [])[:6]:
        print(
            f"    • {s.get('name')} ({s.get('symbol')}): "
            f"{s.get('return_1d_pct'):+.2f}% day | "
            f"z_cs {s.get('cross_section_z')} | β {s.get('beta_spy')}"
        )
    print()
    outliers = data.get("statistical_outliers", [])
    if outliers:
        print("  Statistical outliers:")
        for o in outliers[:5]:
            print(
                f"    • {o.get('symbol')} [{o.get('direction')}]: "
                f"z {o.get('z_score_mover')} ({o.get('day_chg_pct'):+.2f}%)"
            )
        print()
    if assessment:
        print("  Statistical assessment:")
        for key in (
            "market_regime",
            "volatility_regime",
            "trend_signal",
            "mathematical_edge",
        ):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_information_theory(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Regime: {metrics.get('regime_label')} "
        f"(avg H_norm {metrics.get('average_normalized_entropy')}, "
        f"avg Hurst {metrics.get('average_hurst')})"
    )
    print(f"  Methods: {', '.join(meta.get('methods_applied', []))}")
    print()
    print("  Entropy (randomness of returns):")
    for e in sorted(data.get("entropy_results", []), key=lambda x: x.get("normalized_entropy", 0))[:6]:
        print(
            f"    • {e.get('symbol')}: H={e.get('shannon_entropy_bits'):.3f} bits "
            f"(norm {e.get('normalized_entropy'):.3f}) — {e.get('efficiency_label')}"
        )
    print()
    print("  Hurst exponent (memory / persistence):")
    for h in data.get("hurst_results", [])[:6]:
        print(f"    • {h.get('symbol')}: H={h.get('hurst_exponent'):.3f} ({h.get('regime')})")
    print()
    findings = data.get("findings", [])
    if findings:
        print("  Findings:")
        for f in findings[:5]:
            print(f"    • {f.get('title')} — {f.get('practical_implication')}")
        print()
    if assessment:
        print("  Information assessment:")
        if assessment.get("information_conclusion"):
            print(f"    • {assessment['information_conclusion']}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_finance(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("trader_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — Google Finance Beta")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Tape: {metrics.get('trend_label')} "
        f"(opportunity {metrics.get('opportunity_score')})"
    )
    print(
        f"  Momentum: {metrics.get('momentum_score')} | "
        f"Dispersion: {metrics.get('dispersion_score')} | "
        f"Risk/reward: {metrics.get('risk_reward_score')}"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Equity sectors (Google Finance beta):")
    for s in sorted(data.get("sectors", []), key=lambda x: -(x.get("day_chg_pct") or -999))[:6]:
        print(
            f"    • {s.get('google_symbol')} {s.get('name')}: "
            f"{s.get('day_chg_pct'):+.2f}% day | z {s.get('z_score_5d')}"
        )
    print()
    print("  US indices:")
    for i in data.get("indices", [])[:5]:
        print(
            f"    • {i.get('name')}: {i.get('price')} "
            f"({i.get('day_chg_pct'):+.2f}%)"
        )
    print()
    opps = data.get("trading_opportunities", [])
    if opps:
        print("  Top trading opportunities:")
        for o in opps[:6]:
            print(
                f"    • {o.get('symbol')} [{o.get('strategy')}]: "
                f"score {o.get('opportunity_score')} — {o.get('rationale')}"
            )
        print()
    if assessment:
        print("  Trader assessment:")
        for key in ("regime", "sector_rotation", "mathematical_edge", "crypto_signal"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_geopolitics(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('headlines_analyzed', 0)} headlines")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Risk: {metrics.get('risk_label')} ({metrics.get('global_risk_score')})")
    print(f"  Escalation index: {metrics.get('escalation_index')}")
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    for t in data.get("theaters", []):
        if t.get("article_count", 0) > 0:
            print(
                f"  • {t.get('name')}: risk {t.get('risk_score')} "
                f"({t.get('article_count')} articles)"
            )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_datascience(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    mc = meta.get("monte_carlo", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('tickers_analyzed', 0)} tickers")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Regime: {metrics.get('stress_label')} (stress {metrics.get('quant_stress_score')})")
    print(f"  Opportunity score: {metrics.get('opportunity_score')}")
    if mc:
        print(f"  Monte Carlo: {mc.get('simulations')} sims × {mc.get('horizon_days')} days")
    print()
    print("  Factor rankings (momentum):")
    for t in sorted(data.get("tickers", []), key=lambda x: x.get("momentum_score", 0), reverse=True)[:6]:
        print(
            f"    • {t.get('symbol')}: mom {t.get('momentum_score')} | "
            f"z {t.get('z_score_20d'):+.2f} | 20d {t.get('return_20d_pct'):+.2f}% | "
            f"MC P(up) {t.get('mc_prob_up_5d'):.0%}"
        )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_data_steward(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("stewardship_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Regime: {metrics.get('regime_label')} "
        f"(stewardship {metrics.get('stewardship_score')}, "
        f"quality {metrics.get('quality_score')}, "
        f"freshness {metrics.get('freshness_score')})"
    )
    print(
        f"  Catalog: {meta.get('agents_cataloged')} agents, "
        f"{meta.get('sources_cataloged')} sources | "
        f"Open issues: {metrics.get('open_issues')}"
    )
    print()
    print("  Source health:")
    for h in data.get("source_health", [])[:6]:
        print(f"    • {h.get('name')}: {h.get('status')} — {h.get('message')}")
    print()
    present = [a for a in data.get("artifact_quality", []) if a.get("exists")][:6]
    if present:
        print("  Artifact quality:")
        for a in present:
            print(
                f"    • {a.get('filename')}: {a.get('completeness_score'):.0%} complete, "
                f"{a.get('freshness_label')}"
            )
        print()
    issues = data.get("stewardship_issues", [])
    if issues:
        print("  Top stewardship issues:")
        for i in issues[:5]:
            print(f"    • [{i.get('severity')}] {i.get('message')}")
        print()
    if assessment:
        print("  Stewardship assessment:")
        for key in ("stewardship_priority", "governance_signal"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_records_management(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("archivist_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Regime: {metrics.get('regime_label')} "
        f"(archive {metrics.get('archive_score')}, "
        f"compliance {metrics.get('compliance_score')})"
    )
    print(
        f"  Records: {meta.get('record_count')} files, "
        f"{meta.get('volume_bytes', 0):,} bytes | "
        f"Pending actions: {metrics.get('pending_actions')}"
    )
    print()
    snaps = data.get("snapshots_created", [])
    if snaps:
        print("  Snapshots created:")
        for s in snaps:
            print(
                f"    • {s.get('snapshot_id')}: {s.get('files_copied')} files "
                f"({s.get('total_bytes', 0):,} bytes)"
            )
        print()
    by_series: dict[str, int] = {}
    for r in data.get("archive_inventory", []):
        by_series[r.get("series", "?")] = by_series.get(r.get("series", "?"), 0) + 1
    if by_series:
        print("  Inventory by series:")
        for series, count in sorted(by_series.items(), key=lambda x: -x[1]):
            print(f"    • {series}: {count} records")
        print()
    actions = data.get("disposition_actions", [])
    if actions:
        print("  Disposition actions:")
        for a in actions[:5]:
            print(f"    • [{a.get('priority')}] {a.get('action')} {a.get('filename')}")
        print()
    if assessment:
        print("  Archivist assessment:")
        for key in ("archival_priority", "archive_coverage"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_combined_conditional(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("combined_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Regime: {metrics.get('regime_label')} "
        f"(coherence {metrics.get('coherence_score')}, "
        f"dependence {metrics.get('dependence_score')})"
    )
    print(f"  Concepts: {', '.join(meta.get('concepts_applied', []))}")
    print()
    print("  Joint probabilities P(A∩B):")
    for j in data.get("joint_probabilities", [])[:5]:
        print(
            f"    • P({j.get('event_a')}∩{j.get('event_b')}) = "
            f"{j.get('joint_prob'):.0%} ({j.get('label')})"
        )
    print()
    print("  Conditional probabilities P(A|B):")
    for c in data.get("conditional_probabilities", [])[:5]:
        print(
            f"    • P({c.get('event')}|{c.get('condition')}) = "
            f"{c.get('conditional_prob'):.0%} ({c.get('label')})"
        )
    print()
    multi = data.get("multi_conditionals", [])
    if multi:
        print("  Multi-condition P(A|B∩C):")
        for m in multi[:3]:
            print(
                f"    • P({m.get('event')}|{m.get('conditions')}) = "
                f"{m.get('conditional_prob'):.0%}"
            )
        print()
    if assessment:
        print("  Combined assessment:")
        for key in ("independence_signal", "chain_rule_signal", "combined_edge"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_empirical_probability(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("empirical_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Regime: {metrics.get('regime_label')} "
        f"(evidence {metrics.get('evidence_score')}, "
        f"stability {metrics.get('stability_score')})"
    )
    print(f"  Experiments: {', '.join(meta.get('experiments_run', []))}")
    print()
    print("  Frequency estimates:")
    for f in data.get("frequency_estimates", [])[:5]:
        print(
            f"    • {f.get('symbol')} P({f.get('event')}): "
            f"{f.get('empirical_prob'):.0%} "
            f"[{f.get('wilson_ci_low'):.0%}, {f.get('wilson_ci_high'):.0%}] "
            f"n={f.get('trials')}"
        )
    print()
    exps = data.get("rule_experiments", [])
    if exps:
        print("  Rule experiments (in-sample / OOS):")
        for e in exps[:4]:
            print(
                f"    • {e.get('symbol')} {e.get('rule_id')}: "
                f"{e.get('in_sample_win_rate'):.0%} / {e.get('out_of_sample_win_rate'):.0%} "
                f"({'stable' if e.get('stable') else 'unstable'})"
            )
        print()
    if assessment:
        print("  Empirical assessment:")
        for key in ("conditional_signal", "experiment_signal", "experimental_edge"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_events(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    summary = data.get("summary", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('events_tracked', 0)} events")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Critical: {summary.get('critical_count', 0)}")
    by_imp = summary.get("by_impact", {})
    print(
        f"  Impact mix: "
        f"critical {by_imp.get('critical', 0)}, high {by_imp.get('high', 0)}, "
        f"medium {by_imp.get('medium', 0)}, low {by_imp.get('low', 0)}"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Recent events:")
    for e in data.get("events", [])[:8]:
        print(
            f"    • [{e.get('impact', '?').upper()}] {e.get('title', '')[:70]} "
            f"— {e.get('region', '')}"
        )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_grid(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("electrical_assessment", {})
    print()
    print("=" * 60)
    print(
        f"  {meta.get('agent', 'Agent')} — "
        f"{meta.get('markets_monitored', 0)} ISO/RTO markets"
    )
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Stress: {metrics.get('stress_label')} "
        f"({metrics.get('grid_stress_score')})"
    )
    print(
        f"  Renewable index: {metrics.get('renewable_index')} | "
        f"CAISO net demand: {metrics.get('caiso_net_demand_mw', 'n/a')} MW"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Live fuel mix:")
    for f in data.get("fuel_mix", []):
        print(
            f"    • {f.get('market')}: {f.get('total_mw', 0):,.0f} MW | "
            f"renewable {f.get('renewable_pct')}% | gas {f.get('gas_pct')}% | "
            f"wind {f.get('wind_mw', 0):,.0f} | solar {f.get('solar_mw', 0):,.0f}"
        )
    print()
    print("  ISO demand (EIA hourly):")
    for d in sorted(data.get("iso_demand", []), key=lambda x: -x.get("demand_mw", 0))[:5]:
        print(f"    • {d.get('name')}: {d.get('demand_mw', 0):,.0f} MW ({d.get('period')})")
    print()
    prices = data.get("hub_prices", [])
    if prices:
        print("  ERCOT hub LMP:")
        for p in prices:
            print(f"    • {p.get('hub')}: ${p.get('lmp', 0):.2f}/MWh")
        print()
    if assessment:
        print("  Electrical assessment:")
        for key in ("generation_mix", "wholesale_pricing", "storage_dispatch"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_electricity(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("electrical_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — US48 Electric Overview")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Balance: {metrics.get('stress_label')} "
        f"({metrics.get('grid_balance_score')})"
    )
    print(
        f"  Demand: {metrics.get('total_demand_mw', 0):,.0f} MW | "
        f"Net gen: {metrics.get('net_generation_mw', 0):,.0f} MW | "
        f"Gap: {metrics.get('supply_demand_gap_mw', 0):+,.0f} MW"
    )
    print(
        f"  Fuel mix: gas {metrics.get('gas_pct')}% | "
        f"coal {metrics.get('coal_pct')}% | "
        f"renewables {metrics.get('renewable_pct')}%"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Hourly fuel mix:")
    for f in data.get("fuel_mix", [])[:8]:
        print(
            f"    • {f.get('fuel_name')}: {f.get('generation_mwh', 0):,.0f} MWh "
            f"({f.get('share_pct')}%) — {f.get('period')}"
        )
    print()
    print("  ISO demand breakdown:")
    for d in sorted(data.get("iso_breakdown", []), key=lambda x: -x.get("demand_mw", 0))[:6]:
        print(
            f"    • {d.get('region_name')}: {d.get('demand_mw', 0):,.0f} MW "
            f"({d.get('period')})"
        )
    print()
    if assessment:
        print("  Electrical assessment:")
        for key in (
            "supply_demand_balance",
            "fuel_dominance",
            "renewable_penetration",
            "regional_load",
            "gas_reliance",
            "dashboard_note",
        ):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_theoretical_probability(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    markov = data.get("markov_chain", {})
    bayes = data.get("bayesian_inference", {})
    assessment = data.get("probability_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Regime: {metrics.get('regime_label')} "
        f"(conviction {metrics.get('conviction_score')})"
    )
    print(
        f"  Markov state: {markov.get('current_state')} → "
        f"forecast bull {markov.get('one_step_forecast', {}).get('bull')}"
    )
    print(
        f"  Bayesian posterior: {bayes.get('dominant_regime')} "
        f"({bayes.get('posterior', {}).get(bayes.get('dominant_regime', ''), 0)})"
    )
    print(f"  Models: {', '.join(meta.get('models_applied', []))}")
    print()
    print("  Conditional probabilities:")
    for c in data.get("conditional_probabilities", [])[:5]:
        print(
            f"    • P({c.get('event')}|{c.get('condition')}) = "
            f"{c.get('probability'):.0%} ({c.get('label')})"
        )
    print()
    evs = data.get("expected_values", [])
    if evs:
        print("  Expected value / Kelly:")
        for e in evs[:4]:
            print(
                f"    • {e.get('symbol')} {e.get('strategy')}: "
                f"EV {e.get('expected_value_pct'):+.3f}% | "
                f"Kelly {e.get('kelly_fraction'):.1%}"
            )
        print()
    if assessment:
        print("  Probability assessment:")
        for key in ("bayesian_signal", "barrier_risk", "theoretical_edge"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_transportation(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    civil = data.get("civil_assessment", {})
    print()
    print("=" * 60)
    print(
        f"  {meta.get('agent', 'Agent')} — "
        f"{meta.get('resources_cataloged', 0)} DOT resources"
    )
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Stress: {metrics.get('stress_label')} "
        f"({metrics.get('infrastructure_stress_score')})"
    )
    print(
        f"  Freight momentum: {metrics.get('freight_momentum_score')} | "
        f"Unknown bridge designs: {metrics.get('unknown_design_pct')}%"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Top railroad bridge states:")
    for s in data.get("bridge_inventory", {}).get("top_states", [])[:6]:
        print(
            f"    #{s.get('rank')} {s.get('state')}: "
            f"{s.get('bridge_count', 0):,} bridges ({s.get('share_pct')}%)"
        )
    print()
    print("  Recent traffic (week / all / truck %):")
    for w in data.get("traffic", [])[:4]:
        print(
            f"    • {w.get('year')}-W{w.get('week')}: "
            f"all {w.get('all_vehicles_chg_pct'):+.0f}% | "
            f"truck {w.get('truck_chg_pct'):+.0f}%"
        )
    print()
    if civil:
        print("  Civil assessment:")
        for key in ("bridge_condition", "traffic_demand", "freight_corridor"):
            if civil.get(key):
                print(f"    • {civil[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_patents(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    summary = data.get("summary", {})
    print()
    print("=" * 60)
    print(
        f"  {meta.get('agent', 'Agent')} — "
        f"{meta.get('resources_tracked', 0)} resources, "
        f"{meta.get('findings_count', 0)} findings"
    )
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Landscape: {summary.get('landscape_label')} "
        f"(score {summary.get('innovation_score')})"
    )
    print(
        f"  Resources online: {summary.get('resources_online', 0)}/"
        f"{meta.get('resources_tracked', 0)}"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Top sectors:")
    for sector, count in sorted(
        summary.get("by_sector", {}).items(), key=lambda x: -x[1]
    )[:5]:
        print(f"    • {sector.replace('-', ' ').title()}: {count}")
    print()
    print("  Recent findings:")
    for f in data.get("findings", [])[:8]:
        print(
            f"    • [{f.get('sector', '?')}] {f.get('title', '')[:68]} "
            f"— {f.get('source', '')}"
        )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_logistics(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('corridors_monitored', 0)} corridors")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Stress: {metrics.get('stress_label')} ({metrics.get('supply_chain_stress_score')})")
    print(f"  Freight momentum: {metrics.get('freight_momentum_score')}")
    print(f"  Peak congestion: {metrics.get('congestion_score')}")
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    primary = data.get("primary_corridor")
    if primary:
        print(
            f"  Primary view — {primary.get('name')}: "
            f"{primary.get('total_vessels')} vessels | "
            f"density {primary.get('lane_density_score')} | "
            f"congestion {primary.get('congestion_score')}"
        )
        print()
    strategies = data.get("marine_traffic_strategies", {})
    if strategies:
        print("  Marine traffic strategies:")
        for key in ("routing", "anchorage", "freight_mix", "port_priority"):
            if strategies.get(key):
                print(f"    • {strategies[key]}")
        print()
    for c in data.get("corridors", []):
        m = c.get("metrics", {})
        print(
            f"  • {c.get('name')}: {c.get('total_vessels')} vessels | "
            f"density {m.get('lane_density_score')} | congestion {m.get('congestion_score')}"
        )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_research_statistics(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("research_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Regime: {metrics.get('regime_label')} "
        f"(significance {metrics.get('significance_score')}, "
        f"quality {metrics.get('research_quality_score')})"
    )
    print(f"  α = {meta.get('alpha_level', 0.05)} | Methods: {', '.join(meta.get('methods_applied', []))}")
    print()
    print("  Hypothesis tests:")
    for t in data.get("hypothesis_tests", [])[:6]:
        sig = "*" if t.get("significant") else ""
        print(
            f"    • {t.get('symbol')} {t.get('test_id')}: "
            f"t={t.get('statistic'):.3f}, p={t.get('p_value'):.4f}{sig}"
        )
    print()
    print("  OLS regressions (vs SPY):")
    for r in data.get("regressions", [])[:5]:
        print(
            f"    • {r.get('symbol')}: β={r.get('beta'):.2f}, "
            f"R²={r.get('r_squared'):.2f}, α={r.get('alpha_daily'):+.4f}%/day"
        )
    print()
    findings = data.get("research_findings", [])
    if findings:
        print("  Research findings:")
        for f in findings[:5]:
            print(f"    • {f.get('title')} (p={f.get('p_value'):.3f})")
        print()
    if assessment:
        print("  Research assessment:")
        for key in ("research_conclusion", "statistical_edge"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_sales_analytics(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    kpis = data.get("kpis", {})
    assessment = data.get("bi_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — Sales Analytics BI")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Consumer strength: {kpis.get('strength_label')} "
        f"(score {kpis.get('consumer_strength_score')})"
    )
    print(
        f"  Momentum index: {kpis.get('sales_momentum_index')} | "
        f"Breadth: {kpis.get('retail_breadth_pct')}% | "
        f"XLY-XLP: {kpis.get('discretionary_premium_pct'):+.2f}%"
    )
    print(f"  Dashboard: {meta.get('dashboard', 'sales_dashboard.html')}")
    print()
    print("  Category performance (20d):")
    for c in data.get("categories", [])[:6]:
        print(
            f"    • {c.get('label')}: {c.get('avg_return_20d_pct'):+.2f}% "
            f"(breadth {c.get('breadth_pct')}%)"
        )
    print()
    print("  Top retail proxies:")
    for r in sorted(data.get("retailers", []), key=lambda x: -(x.get("momentum_score") or 0))[:5]:
        if r.get("category") == "sector_etf":
            continue
        print(
            f"    • {r.get('symbol')} {r.get('name')}: "
            f"20d {r.get('return_20d_pct'):+.2f}%, momentum {r.get('momentum_score')}"
        )
    print()
    if assessment:
        print("  BI assessment:")
        for key in ("consumer_demand", "bi_insight"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


PRINTERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "combined-conditional": _print_combined_conditional,
    "data-steward": _print_data_steward,
    "datascience": _print_datascience,
    "electricity": _print_electricity,
    "empirical-probability": _print_empirical_probability,
    "events": _print_events,
    "financial-data": _print_financial_data,
    "finance": _print_finance,
    "geopolitics": _print_geopolitics,
    "grid": _print_grid,
    "information-theory": _print_information_theory,
    "logistics": _print_logistics,
    "markets": _print_markets,
    "meteorology": _print_meteorology,
    "patents": _print_patents,
    "records-management": _print_records_management,
    "research-statistics": _print_research_statistics,
    "sales-analytics": _print_sales_analytics,
    "theoretical-probability": _print_theoretical_probability,
    "transportation": _print_transportation,
}

RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "combined-conditional": run_combined_conditional_analysis,
    "data-steward": run_data_steward_analysis,
    "datascience": run_datascience_analysis,
    "electricity": run_electricity_analysis,
    "empirical-probability": run_empirical_probability_analysis,
    "events": run_events_analysis,
    "financial-data": run_financial_data_analysis,
    "finance": run_finance_analysis,
    "geopolitics": run_geopolitics_analysis,
    "grid": run_grid_analysis,
    "information-theory": run_information_theory_analysis,
    "logistics": run_logistics_analysis,
    "markets": run_markets_analysis,
    "meteorology": run_meteorology_analysis,
    "patents": run_patents_analysis,
    "records-management": run_records_management_analysis,
    "research-statistics": run_research_statistics_analysis,
    "sales-analytics": run_sales_analytics_analysis,
    "theoretical-probability": run_theoretical_probability_analysis,
    "transportation": run_transportation_analysis,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finance intelligence agents")
    parser.add_argument(
        "agent",
        nargs="?",
        default="events",
        choices=sorted(RUNNERS.keys()),
        help="Agent to run (default: events)",
    )
    parser.add_argument("-o", "--output", type=Path, help="Write JSON report to this file")
    parser.add_argument("--json", action="store_true", help="Print full JSON to stdout")
    args = parser.parse_args()

    try:
        result = RUNNERS[args.agent](output=args.output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        PRINTERS[args.agent](result)
        if args.output:
            print(f"  Full report saved to {args.output}")
            if args.agent == "events":
                tracker = args.output.parent / "world_events_tracker.json"
                if tracker.exists():
                    print(f"  Web tracker import file: {tracker}")
            if args.agent == "patents":
                catalog = args.output.parent / "patent_resources.json"
                if catalog.exists():
                    print(f"  Resource catalog: {catalog}")
            if args.agent == "transportation":
                catalog = args.output.parent / "dot_resources.json"
                if catalog.exists():
                    print(f"  DOT resource catalog: {catalog}")
            if args.agent == "grid":
                catalog = args.output.parent / "grid_markets.json"
                if catalog.exists():
                    print(f"  Grid markets catalog: {catalog}")
            if args.agent == "electricity":
                catalog = args.output.parent / "eia_grid_monitor_views.json"
                if catalog.exists():
                    print(f"  EIA Grid Monitor views: {catalog}")
            if args.agent == "logistics":
                catalog = args.output.parent / "marine_traffic_corridors.json"
                if catalog.exists():
                    print(f"  MarineTraffic corridor catalog: {catalog}")
            if args.agent == "financial-data":
                catalog = args.output.parent / "yahoo_finance_views.json"
                if catalog.exists():
                    print(f"  Yahoo Finance views: {catalog}")
            if args.agent == "finance":
                catalog = args.output.parent / "google_finance_views.json"
                if catalog.exists():
                    print(f"  Google Finance views: {catalog}")
            if args.agent == "theoretical-probability":
                catalog = args.output.parent / "probability_models.json"
                if catalog.exists():
                    print(f"  Probability models catalog: {catalog}")
            if args.agent == "empirical-probability":
                catalog = args.output.parent / "empirical_experiments.json"
                if catalog.exists():
                    print(f"  Empirical experiments catalog: {catalog}")
            if args.agent == "combined-conditional":
                catalog = args.output.parent / "probability_concepts.json"
                if catalog.exists():
                    print(f"  Probability concepts catalog: {catalog}")
            if args.agent == "research-statistics":
                catalog = args.output.parent / "statistical_methods.json"
                if catalog.exists():
                    print(f"  Statistical methods catalog: {catalog}")
            if args.agent == "information-theory":
                catalog = args.output.parent / "information_theory_methods.json"
                if catalog.exists():
                    print(f"  Information theory methods catalog: {catalog}")
            if args.agent == "sales-analytics":
                feed = args.output.parent / "sales_dashboard_data.json"
                if feed.exists():
                    print(f"  Sales dashboard feed: {feed}")
                panels = args.output.parent / "sales_dashboard_panels.json"
                if panels.exists():
                    print(f"  Dashboard panels: {panels}")
                print(f"  Open dashboard: open_sales_dashboard.bat")
            if args.agent == "data-steward":
                catalog = args.output.parent / "data_catalog.json"
                if catalog.exists():
                    print(f"  Data catalog: {catalog}")
                lineage = args.output.parent / "data_lineage.json"
                if lineage.exists():
                    print(f"  Data lineage: {lineage}")
            if args.agent == "records-management":
                catalog = args.output.parent / "archive_catalog.json"
                if catalog.exists():
                    print(f"  Archive catalog: {catalog}")
                retention = args.output.parent / "retention_schedule.json"
                if retention.exists():
                    print(f"  Retention schedule: {retention}")
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())