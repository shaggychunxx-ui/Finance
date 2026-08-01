#!/usr/bin/env python3
"""Rebuild long strategy plan from current portfolio (prefer dry-run).

Usage:
  python rebuild_trading_plan.py
  python rebuild_trading_plan.py --force-live   # only if dry_run is off in config
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_paths import OUTPUT, ensure_app_path

ensure_app_path()


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild long strategy plan")
    parser.add_argument(
        "--force-live",
        action="store_true",
        help="Allow live execute path if config dry_run is false (default: plan only)",
    )
    args = parser.parse_args()

    from etrade_api.config import get_selected_account, load_config, read_config_raw
    from etrade_api.oauth import load_tokens
    from portfolio_generator import generate_portfolio, save_portfolio
    from strategy_engine import build_strategy_plan, preview_orders, save_strategy_plan

    raw = read_config_raw(ROOT / "etrade_config.json")
    worker = raw.get("background_worker") if isinstance(raw.get("background_worker"), dict) else {}
    dry = bool(worker.get("dry_run", True))
    if not dry and not args.force_live:
        dry = True
        print("Config dry_run=false but rebuilding plan in dry-run mode (pass --force-live to override).")

    portfolio = generate_portfolio(OUTPUT)
    save_portfolio(portfolio, OUTPUT / "portfolio.json")
    print(f"Portfolio holdings: {len(portfolio.get('holdings') or [])}")

    try:
        cfg = load_config(ROOT / "etrade_config.json")
        tokens = load_tokens(cfg.token_path, cfg.sandbox)
    except Exception as exc:
        print(f"E*TRADE config/tokens unavailable ({exc}) — offline plan stub only.")
        tokens = None
        cfg = None

    if not tokens or cfg is None:
        plan_path = OUTPUT / "strategy_plan.json"
        stub = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "account_id_key": "OFFLINE",
            "account_name": "offline rebuild",
            "sandbox": True,
            "orders": [],
            "target_holdings": portfolio.get("holdings") or [],
            "meta": {"dry_run": True, "offline": True, "reason": "no_oauth_tokens"},
        }
        plan_path.write_text(json.dumps(stub, indent=2), encoding="utf-8")
        print(f"Wrote offline stub plan → {plan_path}")
        return 0

    from etrade_api.client import ETradeClient

    client = ETradeClient(cfg, tokens)
    acct = get_selected_account(ROOT / "etrade_config.json") or {}
    key = str(acct.get("account_id_key") or "")
    if not key:
        print("No selected_account — offline stub.")
        return 1

    plan = build_strategy_plan(
        client,
        key,
        account_name=str(acct.get("display_label") or ""),
        portfolio=portfolio,
    )
    plan = preview_orders(client, plan)
    save_strategy_plan(plan)
    n = len(plan.orders)
    print(f"Strategy plan orders: {n} (previewed, dry_run={dry})")
    print(f"Saved → {OUTPUT / 'strategy_plan.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
