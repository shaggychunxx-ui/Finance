"""Configuration for the E*TRADE API helper: credentials + sandbox/production URLs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "etrade_config.json"
DEFAULT_TOKEN_PATH = Path(__file__).resolve().parent.parent / "etrade_tokens.json"

SANDBOX_BASE = "https://apisb.etrade.com"
PRODUCTION_BASE = "https://api.etrade.com"
AUTHORIZE_URL = "https://us.etrade.com/e/t/etws/authorize"
DEFAULT_CALLBACK_PORT = 8765
DEFAULT_CALLBACK_PATH = "/callback"

KEY_PLACEHOLDER = "YOUR_CONSUMER_KEY"
SECRET_PLACEHOLDER = "YOUR_CONSUMER_SECRET"


def sanitize_credential(value: str, placeholder: str) -> str:
    cleaned = (value or "").strip()
    if placeholder:
        while cleaned.startswith(placeholder):
            cleaned = cleaned[len(placeholder) :].strip()
    # Keys copied from email/web often include stray spaces or line breaks.
    cleaned = "".join(cleaned.split())
    return cleaned


def credential_hint(value: str) -> str:
    cleaned = sanitize_credential(value, KEY_PLACEHOLDER)
    if len(cleaned) <= 8:
        return cleaned or "(empty)"
    return f"{cleaned[:4]}…{cleaned[-4:]}"


def build_config(
    consumer_key: str,
    consumer_secret: str,
    *,
    sandbox: bool = True,
    callback_url: str = f"http://127.0.0.1:{DEFAULT_CALLBACK_PORT}{DEFAULT_CALLBACK_PATH}",
    use_oob: bool = False,
    config_path: Path = DEFAULT_CONFIG_PATH,
    token_path: Path = DEFAULT_TOKEN_PATH,
) -> ETradeConfig:
    key = sanitize_credential(consumer_key, KEY_PLACEHOLDER)
    secret = sanitize_credential(consumer_secret, SECRET_PLACEHOLDER)
    if not key or not secret:
        raise ValueError("consumer_key and consumer_secret are required")
    if key == KEY_PLACEHOLDER or secret == SECRET_PLACEHOLDER:
        raise ValueError("Replace placeholder API credentials with your real E*TRADE keys.")
    return ETradeConfig(
        consumer_key=key,
        consumer_secret=secret,
        sandbox=sandbox,
        callback_url=callback_url,
        use_oob=use_oob,
        config_path=config_path,
        token_path=token_path,
    )


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

    consumer_key = sanitize_credential(
        raw.get("consumer_key") or os.getenv("ETRADE_CONSUMER_KEY", ""),
        KEY_PLACEHOLDER,
    )
    consumer_secret = sanitize_credential(
        raw.get("consumer_secret") or os.getenv("ETRADE_CONSUMER_SECRET", ""),
        SECRET_PLACEHOLDER,
    )
    if not consumer_key or not consumer_secret:
        raise ValueError("consumer_key and consumer_secret are required in etrade_config.json")
    if consumer_key == KEY_PLACEHOLDER or consumer_secret == SECRET_PLACEHOLDER:
        raise ValueError("Replace YOUR_CONSUMER_KEY and YOUR_CONSUMER_SECRET with your real API credentials.")

    token_path = Path(raw.get("token_path", DEFAULT_TOKEN_PATH))
    if not token_path.is_absolute():
        token_path = (config_path.parent / token_path).resolve()

    return ETradeConfig(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        sandbox=bool(raw.get("sandbox", True)),
        callback_url=raw.get("callback_url", ETradeConfig.callback_url),
        use_oob=bool(raw.get("use_oob", False)),
        config_path=config_path,
        token_path=token_path,
    )


def read_config_raw(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return {}
    try:
        with config_path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}


def write_config_raw(path: str | Path, data: dict[str, Any]) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def get_selected_account(path: str | Path | None = None) -> dict[str, Any] | None:
    raw = read_config_raw(path)
    selected = raw.get("selected_account")
    if isinstance(selected, dict):
        key = str(selected.get("account_id_key") or "").strip()
        if key:
            return {
                "account_id_key": key,
                "display_label": str(selected.get("display_label") or "").strip(),
                "confirmed_at": selected.get("confirmed_at"),
            }
    return None


def save_selected_account(
    account_id_key: str,
    *,
    display_label: str = "",
    path: str | Path | None = None,
) -> None:
    key = (account_id_key or "").strip()
    if not key:
        raise ValueError("account_id_key is required")
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw = read_config_raw(config_path)
    raw["selected_account"] = {
        "account_id_key": key,
        "display_label": display_label.strip(),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    write_config_raw(config_path, raw)


def clear_selected_account(path: str | Path | None = None) -> None:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw = read_config_raw(config_path)
    if "selected_account" in raw:
        del raw["selected_account"]
        write_config_raw(config_path, raw)
