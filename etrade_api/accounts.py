"""Parse E*TRADE account API responses."""

from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _pick_field(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _humanize_label(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if cleaned.isupper() and ("_" in cleaned or len(cleaned) > 4):
        return cleaned.replace("_", " ").title()
    return cleaned


def format_account_label(acct: dict[str, Any]) -> str:
    name = _pick_field(acct, "account_name", "accountName")
    desc = _humanize_label(_pick_field(acct, "account_desc", "accountDesc"))
    mode = _pick_field(acct, "account_mode", "accountMode")
    acct_type = _humanize_label(_pick_field(acct, "account_type", "accountType"))
    account_id = _pick_field(acct, "account_id", "accountId")
    tail = account_id[-4:] if len(account_id) >= 4 else account_id

    primary = name or desc or acct_type or "Account"
    if primary.casefold() == acct_type.casefold() and desc:
        primary = desc
    parts = [primary]

    secondary = desc if desc and desc.casefold() != primary.casefold() else ""
    if not secondary and mode and mode.casefold() != primary.casefold():
        secondary = mode
    if secondary:
        parts.append(secondary)
    elif mode and mode.casefold() != primary.casefold():
        parts.append(mode)

    if tail:
        parts.append(f"#{tail}")

    label = " \u00b7 ".join(parts)
    status = _pick_field(acct, "account_status", "accountStatus").upper()
    if status == "CLOSED":
        label += " (Closed)"
    return label


def parse_accounts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("AccountListResponse", payload)
    accounts_wrapper = response.get("Accounts") or response.get("accounts") or {}
    if isinstance(accounts_wrapper, list):
        account_items = accounts_wrapper
    elif isinstance(accounts_wrapper, dict):
        account_items = _as_list(accounts_wrapper.get("Account") or accounts_wrapper.get("account"))
    else:
        account_items = []

    out: list[dict[str, Any]] = []
    for acct in account_items:
        if not isinstance(acct, dict):
            continue
        parsed = {
            "account_id": _pick_field(acct, "accountId", "account_id"),
            "account_id_key": _pick_field(acct, "accountIdKey", "account_id_key"),
            "account_name": _pick_field(acct, "accountName", "account_name"),
            "account_desc": _pick_field(acct, "accountDesc", "account_desc"),
            "account_mode": _pick_field(acct, "accountMode", "account_mode"),
            "account_type": _pick_field(acct, "accountType", "account_type"),
            "account_status": _pick_field(acct, "accountStatus", "account_status"),
            "institution_type": _pick_field(acct, "institutionType", "institution_type"),
        }
        parsed["display_label"] = format_account_label(parsed)
        out.append(parsed)

    out.sort(key=lambda item: (item.get("account_status") != "ACTIVE", item.get("display_label", "")))
    return out


def accounts_look_like_sandbox_demo(accounts: list[dict[str, Any]]) -> bool:
    if not accounts:
        return False
    demo_name_prefixes = ("nickname-", "nick name-", "test", "demo", "sandbox")
    demo_hits = 0
    for acct in accounts:
        name = _pick_field(acct, "account_name", "accountName").casefold()
        if any(name.startswith(prefix) for prefix in demo_name_prefixes):
            demo_hits += 1
    return demo_hits >= max(1, len(accounts) // 2)


def parse_balance(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("BalanceResponse", payload)
    computed = response.get("Computed", {}) or {}
    if not isinstance(computed, dict):
        computed = {}
    real_time = response.get("RealTimeValues", {}) or {}
    if not isinstance(real_time, dict):
        real_time = {}
    nested_rt = computed.get("RealTimeValues", {}) or {}
    if not isinstance(nested_rt, dict):
        nested_rt = {}

    total = (
        real_time.get("totalAccountValue")
        or nested_rt.get("totalAccountValue")
        or computed.get("totalAccountValue")
        or response.get("accountBalance")
    )
    cash_bp = _float(computed.get("cashBuyingPower"))
    margin_bp = _float(computed.get("marginBuyingPower"))
    cash_avail = _float(computed.get("cashAvailableForInvestment"))
    net_cash = _float(computed.get("netCash"))
    buying_power = cash_bp or margin_bp or cash_avail or net_cash

    return {
        "total_account_value": _float(total),
        "cash_buying_power": buying_power,
        "cash_available_for_investment": cash_avail,
        "margin_buying_power": margin_bp,
        "net_cash": net_cash,
    }


def parse_portfolio(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("PortfolioResponse", payload)
    account_portfolio = response.get("AccountPortfolio", [])
    positions: list[dict[str, Any]] = []
    for block in _as_list(account_portfolio):
        for pos in _as_list(block.get("Position")):
            if not isinstance(pos, dict):
                continue
            product = pos.get("Product", {}) or {}
            symbol = product.get("symbol", "")
            qty = _float(pos.get("quantity"))
            market_value = _float(pos.get("marketValue"))
            price = _float(pos.get("Quick", {}).get("lastTrade")) or _float(pos.get("pricePaid"))
            if not symbol or qty == 0:
                continue
            positions.append(
                {
                    "symbol": symbol.upper(),
                    "quantity": qty,
                    "market_value": market_value,
                    "price": price,
                    "cost_basis": _float(pos.get("pricePaid")),
                    "position_type": pos.get("positionType", "LONG"),
                }
            )
    return positions


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0