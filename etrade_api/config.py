"""Configuration for the E*TRADE API helper: credentials + sandbox/production URLs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "etrade_config.json"
DEFAULT_TOKEN_PATH = Path(__file__).resolve().parent.parent / "etrade_tokens.json"

SANDBOX_BASE = "https://apisb.etrade.com"
PRODUCTION_BASE = "https://api.etrade.com"
AUTHORIZE_URL = "https://us.etrade.com/e/t/etws/authorize"
DEFAULT_CALLBACK_PORT = 8765
DEFAULT_CALLBACK_PATH = "/callback"


@dataclass
class ETradeConfig:
    consumer_key: str
    consumer_secret: str
    sandbox: bool = True
    callback_url: str = f"http://127.0.0.1:{DEFAULT_CALLBACK_PORT}{DEFAULT_CALLBACK_PATH}"
    use_oob: bool = False
    config_path: Path = DEFAULT_CONFIG_PATH
    token_path: Path = DEFAULT_TOKEN_PATH

    @property
    def api_base(self) -> str:
        return SANDBOX_BASE if self.sandbox else PRODUCTION_BASE


def load_config(path: str | Path | None = None) -> ETradeConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(
            f"Missing E*TRADE config at {config_path}. "
            f"Copy etrade_config.example.json to etrade_config.json and add your keys."
        )

    with config_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    consumer_key = raw.get("consumer_key") or os.getenv("ETRADE_CONSUMER_KEY", "")
    consumer_secret = raw.get("consumer_secret") or os.getenv("ETRADE_CONSUMER_SECRET", "")
    if not consumer_key or not consumer_secret:
        raise ValueError("consumer_key and consumer_secret are required in etrade_config.json")

    return ETradeConfig(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        sandbox=bool(raw.get("sandbox", True)),
        callback_url=raw.get("callback_url", ETradeConfig.callback_url),
        use_oob=bool(raw.get("use_oob", False)),
        config_path=config_path,
        token_path=Path(raw.get("token_path", DEFAULT_TOKEN_PATH)),
    )
