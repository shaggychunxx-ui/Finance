"""CLI entry point for the E*TRADE API helper."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from .client import ETradeClient
from .config import ETradeConfig, load_config
from .oauth import authenticate, load_tokens, renew_access_token, revoke_access_token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="E*TRADE API helper: OAuth auth + market endpoints (sandbox or production)."
    )
    parser.add_argument("--config", help="Path to etrade_config.json")
    parser.add_argument(
        "--sandbox",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force sandbox (default) or production mode",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Run OAuth flow and save access token")
    sub.add_parser("renew", help="Renew inactive access token")
    sub.add_parser("revoke", help="Revoke access token")
    sub.add_parser("status", help="Show saved token metadata")

    quotes = sub.add_parser("quotes", help="Get market quotes")
    quotes.add_argument("symbols", help="Comma-separated list of ticker symbols")
    quotes.add_argument("--detail-flag", default="ALL")

    lookup = sub.add_parser("lookup", help="Search symbols by company name")
    lookup.add_argument("search", help="Search text, e.g. company name")

    option_dates = sub.add_parser("option-dates", help="List option expiration dates")
    option_dates.add_argument("symbol")
    option_dates.add_argument("--expiry-type")

    options = sub.add_parser("options", help="Get option chain")
    options.add_argument("symbol")
    options.add_argument("--year", type=int, dest="expiry_year")
    options.add_argument("--month", type=int, dest="expiry_month")
    options.add_argument("--day", type=int, dest="expiry_day")
    options.add_argument("--strike-near", type=float, dest="strike_price_near")
    options.add_argument("--no-of-strikes", type=int, dest="no_of_strikes")
    options.add_argument("--chain-type", dest="chain_type")

    return parser


def _resolve_config(args: argparse.Namespace) -> ETradeConfig:
    config = load_config(args.config)
    if args.sandbox is not None:
        config.sandbox = args.sandbox
    return config


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = _resolve_config(args)

        if args.command == "auth":
            authenticate(config)
            print("Authentication complete. Tokens saved to", config.token_path)
            return 0

        if args.command == "renew":
            tokens = load_tokens(config.token_path, config.sandbox)
            if not tokens:
                raise RuntimeError("No saved token to renew. Run: python -m etrade_api auth")
            renew_access_token(config, tokens)
            print("Access token renewed.")
            return 0

        if args.command == "revoke":
            tokens = load_tokens(config.token_path, config.sandbox)
            if not tokens:
                raise RuntimeError("No saved token to revoke.")
            revoke_access_token(config, tokens)
            print("Access token revoked.")
            return 0

        if args.command == "status":
            tokens = load_tokens(config.token_path, config.sandbox)
            if not tokens:
                print("No saved token found.")
                return 1
            age_minutes = (time.time() - tokens.created_at) / 60
            print(f"Token path: {config.token_path}")
            print(f"Sandbox: {tokens.sandbox}")
            print(f"Created: {age_minutes:.1f} minutes ago")
            return 0

        client = ETradeClient(config)

        if args.command == "quotes":
            symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
            _print_json(client.get_quotes(symbols, detail_flag=args.detail_flag))
            return 0

        if args.command == "lookup":
            _print_json(client.lookup(args.search))
            return 0

        if args.command == "option-dates":
            _print_json(
                client.get_option_expire_dates(args.symbol, expiry_type=args.expiry_type)
            )
            return 0

        if args.command == "options":
            _print_json(
                client.get_option_chains(
                    args.symbol,
                    expiry_year=args.expiry_year,
                    expiry_month=args.expiry_month,
                    expiry_day=args.expiry_day,
                    strike_price_near=args.strike_price_near,
                    no_of_strikes=args.no_of_strikes,
                    chain_type=args.chain_type,
                )
            )
            return 0

        parser.error(f"Unknown command: {args.command}")
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
