"""Track agent prediction accuracy and weight high performers in fusion/trading."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

HISTORY_ROOT = OUTPUT / "history"
PENDING_FILE = HISTORY_ROOT / "prediction_pending.json"
ACCURACY_FILE = HISTORY_ROOT / "prediction_accuracy.json"

HORIZON_HOURS = {"24h": 24, "1wk": 168, "1mo": 720, "1yr": 8760}
HORIZON_MOVE_PCT = {"24h": 0.5, "1wk": 1.5, "1mo": 3.0, "1yr": 8.0}
MAGNITUDE_TOLERANCE_PCT = {"24h": 1.0, "1wk": 2.5, "1mo": 5.0, "1yr": 12.0}
DEFAULT_HORIZON = "24h"
MAX_PENDING = 4000
MAX_SCORED = 2500
MIN_SAMPLES_FOR_WEIGHT = 8
MIN_SAMPLES_FOR_MAGNITUDE = 4
DIRECTION_WEIGHT = 0.6
MAGNITUDE_WEIGHT = 0.4
SKIP_SOURCES = frozenset({"etrade", "history", "market-predictor"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _bias_direction(bias: str) -> str:
    b = str(bias or "").upper()
    if b == "BULLISH":
        return "up"
    if b == "BEARISH":
        return "down"
    return "flat"


def _actual_direction(change_pct: float, *, horizon: str) -> str:
    threshold = HORIZON_MOVE_PCT.get(horizon, 0.5)
    if change_pct > threshold:
        return "up"
    if change_pct < -threshold:
        return "down"
    return "flat"


def _prediction_hit(predicted: str, actual: str) -> bool:
    predicted = str(predicted or "flat").lower()
    actual = str(actual or "flat").lower()
    if predicted == "flat":
        return actual == "flat"
    if actual == "flat":
        return False
    return predicted == actual


def _predicted_return_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _magnitude_hit(
    *,
    predicted_direction: str,
    actual_direction: str,
    predicted_return_pct: float | None,
    actual_return_pct: float,
    horizon: str,
) -> bool | None:
    """True when direction matches and return size is within horizon tolerance."""
    if predicted_return_pct is None:
        return None
    if not _prediction_hit(predicted_direction, actual_direction):
        return False
    tolerance = float(MAGNITUDE_TOLERANCE_PCT.get(horizon, 1.0))
    if str(predicted_direction).lower() == "flat":
        return abs(actual_return_pct) <= tolerance
    return abs(actual_return_pct - predicted_return_pct) <= max(
        tolerance,
        abs(predicted_return_pct) * 0.5,
    )


def _quote_prices() -> dict[str, float]:
    prices: dict[str, float] = {}
    enhanced = _load_json(OUTPUT / "etrade_enhanced_quotes.json")
    if isinstance(enhanced, dict):
        for sym, quote in (enhanced.get("quotes") or {}).items():
            if not isinstance(quote, dict):
                continue
            last = quote.get("last_trade")
            try:
                if last is not None:
                    prices[str(sym).upper()] = float(last)
            except (TypeError, ValueError):
                continue
    return prices


def _pending_store() -> dict[str, Any]:
    data = _load_json(PENDING_FILE)
    if isinstance(data, dict):
        data.setdefault("predictions", [])
        return data
    return {"predictions": [], "updated_at": _now_iso()}


def _accuracy_store() -> dict[str, Any]:
    data = _load_json(ACCURACY_FILE)
    if isinstance(data, dict):
        data.setdefault("agents", {})
        data.setdefault("scored", [])
        data.setdefault("leaderboard", [])
        return data
    return {
        "objective": "maximize_prediction_accuracy",
        "agents": {},
        "scored": [],
        "leaderboard": [],
        "updated_at": _now_iso(),
    }


def _append_prediction(
    pending: list[dict[str, Any]],
    *,
    agent_id: str,
    symbol: str,
    horizon: str,
    predicted_direction: str,
    confidence: float,
    predicted_return_pct: float | None,
    price_at_prediction: float | None,
    cycle_id: str,
    recorded_at: str,
    regime_posture: str = "",
    event_day: bool = False,
    sector_hint: str = "",
) -> None:
    from agent_fusion import agent_in_domain, is_event_day, score_symbol_allowed

    sym = str(symbol or "").strip().upper()
    aid = str(agent_id or "").strip()
    if not sym or not aid or aid in SKIP_SOURCES:
        return
    if not agent_in_domain(aid, sym, sector_hint=sector_hint):
        return
    try:
        px = float(price_at_prediction) if price_at_prediction is not None else None
    except (TypeError, ValueError):
        px = None
    if not score_symbol_allowed(sym, px):
        return
    horizon = horizon if horizon in HORIZON_HOURS else DEFAULT_HORIZON
    direction = str(predicted_direction or "flat").lower()
    if direction not in {"up", "down", "flat"}:
        direction = "flat"
    pred_id = f"{cycle_id}:{aid}:{sym}:{horizon}"
    if any(p.get("id") == pred_id for p in pending):
        return
    pending.append(
        {
            "id": pred_id,
            "agent_id": aid,
            "symbol": sym,
            "horizon": horizon,
            "predicted_direction": direction,
            "predicted_return_pct": predicted_return_pct,
            "confidence": round(max(0.05, min(0.99, float(confidence or 0.5))), 3),
            "price_at_prediction": price_at_prediction,
            "recorded_at": recorded_at,
            "cycle_id": cycle_id,
            "regime_posture": regime_posture or "neutral",
            "event_day": bool(event_day),
        }
    )


def _extract_from_agent_file(
    agent_id: str,
    data: dict[str, Any],
    *,
    cycle_id: str,
    recorded_at: str,
    quotes: dict[str, float],
    pending: list[dict[str, Any]],
    regime_posture: str = "neutral",
    event_day: bool = False,
) -> None:
    from agent_fusion import estimate_return_from_bias
    preds = data.get("predictions", {})
    if isinstance(preds, dict):
        for horizon, rows in preds.items():
            if horizon not in HORIZON_HOURS:
                continue
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                sym = row.get("symbol", "")
                price = row.get("price_at_prediction")
                if price is None and sym:
                    price = quotes.get(str(sym).upper())
                _append_prediction(
                    pending,
                    agent_id=agent_id,
                    symbol=str(sym),
                    horizon=horizon,
                    predicted_direction=str(row.get("predicted_direction", "flat")),
                    confidence=float(row.get("confidence", 0.5)),
                    predicted_return_pct=row.get("predicted_return_pct"),
                    price_at_prediction=float(price) if price is not None else None,
                    cycle_id=cycle_id,
                    recorded_at=recorded_at,
                    regime_posture=regime_posture,
                    event_day=event_day,
                )

    for sig in data.get("market_signals", []):
        if not isinstance(sig, dict):
            continue
        direction = _bias_direction(sig.get("bias", "NEUTRAL"))
        conf = 0.55 if direction == "up" else 0.45 if direction == "down" else 0.35
        sector = str(sig.get("sector", ""))
        for ticker in sig.get("tickers", []):
            sym = str(ticker).upper()
            _append_prediction(
                pending,
                agent_id=agent_id,
                symbol=sym,
                horizon=DEFAULT_HORIZON,
                predicted_direction=direction,
                confidence=conf,
                predicted_return_pct=estimate_return_from_bias(direction, confidence=conf),
                price_at_prediction=quotes.get(sym),
                cycle_id=cycle_id,
                recorded_at=recorded_at,
                regime_posture=regime_posture,
                event_day=event_day,
                sector_hint=sector,
            )

    if agent_id == "finance":
        for opp in data.get("trading_opportunities", []):
            if not isinstance(opp, dict):
                continue
            score = float(opp.get("opportunity_score", 0))
            direction = "up" if score >= 0.35 else "flat"
            sym = str(opp.get("symbol", "")).upper()
            conf = min(0.9, 0.45 + score * 0.2)
            _append_prediction(
                pending,
                agent_id=agent_id,
                symbol=sym,
                horizon=DEFAULT_HORIZON,
                predicted_direction=direction,
                confidence=conf,
                predicted_return_pct=estimate_return_from_bias(direction, confidence=conf),
                price_at_prediction=opp.get("price") or quotes.get(sym),
                cycle_id=cycle_id,
                recorded_at=recorded_at,
                regime_posture=regime_posture,
                event_day=event_day,
            )

    if agent_id == "datascience":
        for pick in data.get("top_picks", []):
            if not isinstance(pick, dict):
                continue
            sym = str(pick.get("symbol", "")).upper()
            conf = float(pick.get("confidence", 0.55))
            ret = pick.get("expected_return_pct", pick.get("predicted_return_pct"))
            if ret is None:
                ret = estimate_return_from_bias("up", confidence=conf)
            _append_prediction(
                pending,
                agent_id=agent_id,
                symbol=sym,
                horizon=DEFAULT_HORIZON,
                predicted_direction="up",
                confidence=conf,
                predicted_return_pct=ret,
                price_at_prediction=pick.get("price") or quotes.get(sym),
                cycle_id=cycle_id,
                recorded_at=recorded_at,
                regime_posture=regime_posture,
                event_day=event_day,
            )


def record_cycle_predictions(*, cycle_id: str | None = None) -> int:
    """Capture directional predictions from the latest agent cycle."""
    from agent_fusion import current_regime, is_event_day
    from agents.platform_catalog import active_agent_sources

    recorded_at = _now_iso()
    cycle_id = cycle_id or _now().strftime("%Y%m%dT%H%M%SZ")
    quotes = _quote_prices()
    regime = current_regime()
    posture = str(regime.get("posture", "neutral"))
    event_day = is_event_day(recorded_at=recorded_at)
    store = _pending_store()
    pending: list[dict[str, Any]] = list(store.get("predictions") or [])
    before = len(pending)

    for src in active_agent_sources(check_remote=False):
        path = OUTPUT / src["file"]
        if not path.exists():
            continue
        data = _load_json(path)
        if isinstance(data, dict):
            _extract_from_agent_file(
                src["id"],
                data,
                cycle_id=cycle_id,
                recorded_at=recorded_at,
                quotes=quotes,
                pending=pending,
                regime_posture=posture,
                event_day=event_day,
            )

    predictions_path = OUTPUT / "market_predictions.json"
    fused = _load_json(predictions_path)
    if isinstance(fused, dict):
        for horizon, rows in (fused.get("predictions") or {}).items():
            if horizon not in HORIZON_HOURS:
                continue
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol", "")).upper()
                price = row.get("price_at_prediction") or quotes.get(sym)
                for source in row.get("sources") or []:
                    _append_prediction(
                        pending,
                        agent_id=str(source),
                        symbol=sym,
                        horizon=horizon,
                        predicted_direction=str(row.get("predicted_direction", "flat")),
                        confidence=float(row.get("confidence", 0.5)),
                        predicted_return_pct=row.get("predicted_return_pct"),
                        price_at_prediction=float(price) if price is not None else None,
                        cycle_id=cycle_id,
                        recorded_at=recorded_at,
                        regime_posture=posture,
                        event_day=event_day,
                    )

    store["predictions"] = pending[-MAX_PENDING:]
    store["updated_at"] = recorded_at
    _write_json(PENDING_FILE, store)
    return len(pending) - before


def score_matured_predictions() -> int:
    """Resolve predictions whose horizon has elapsed and update accuracy stats."""
    from price_history import clear_yahoo_cache, record_prices, resolve_price_at

    store = _pending_store()
    pending: list[dict[str, Any]] = list(store.get("predictions") or [])
    if not pending:
        return 0

    quotes = _quote_prices()
    record_prices(quotes)
    clear_yahoo_cache()

    accuracy = _accuracy_store()
    scored: list[dict[str, Any]] = list(accuracy.get("scored") or [])
    now = _now()
    remaining: list[dict[str, Any]] = []
    newly_scored = 0

    for pred in pending:
        recorded = _parse_iso(pred.get("recorded_at"))
        horizon = str(pred.get("horizon") or DEFAULT_HORIZON)
        hours = HORIZON_HOURS.get(horizon, 24)
        if not recorded or (now - recorded) < timedelta(hours=hours):
            remaining.append(pred)
            continue

        sym = str(pred.get("symbol", "")).upper()
        horizon_end = recorded + timedelta(hours=hours)
        start_price = pred.get("price_at_prediction")
        latest_quote = quotes.get(sym)
        try:
            start_price = float(start_price) if start_price is not None else None
        except (TypeError, ValueError):
            start_price = None

        if not start_price or start_price <= 0:
            if latest_quote and latest_quote > 0:
                start_price = float(latest_quote)
            else:
                remaining.append(pred)
                continue

        end_price, price_source = resolve_price_at(
            sym,
            horizon_end,
            latest_quote=float(latest_quote) if latest_quote else None,
        )
        if not end_price or end_price <= 0:
            remaining.append(pred)
            continue

        return_pct = (end_price - start_price) / start_price * 100.0
        actual = _actual_direction(return_pct, horizon=horizon)
        predicted = str(pred.get("predicted_direction", "flat")).lower()
        hit = _prediction_hit(predicted, actual)
        conf = float(pred.get("confidence", 0.5))
        predicted_return_pct = _predicted_return_value(pred.get("predicted_return_pct"))
        magnitude_hit = _magnitude_hit(
            predicted_direction=predicted,
            actual_direction=actual,
            predicted_return_pct=predicted_return_pct,
            actual_return_pct=return_pct,
            horizon=horizon,
        )
        magnitude_error_pct = (
            round(abs(return_pct - predicted_return_pct), 3)
            if predicted_return_pct is not None
            else None
        )

        outcome = 1.0 if hit else 0.0
        scored.append(
            {
                "agent_id": pred.get("agent_id"),
                "symbol": sym,
                "horizon": horizon,
                "predicted_direction": predicted,
                "actual_direction": actual,
                "predicted_return_pct": (
                    round(predicted_return_pct, 3) if predicted_return_pct is not None else None
                ),
                "actual_return_pct": round(return_pct, 3),
                "magnitude_error_pct": magnitude_error_pct,
                "magnitude_hit": magnitude_hit,
                "price_source": price_source,
                "horizon_end_at": horizon_end.isoformat(),
                "start_price": round(start_price, 4),
                "end_price": round(end_price, 4),
                "hit": hit,
                "confidence": conf,
                "brier_term": round((conf - outcome) ** 2, 4),
                "regime_posture": pred.get("regime_posture", "neutral"),
                "event_day": bool(pred.get("event_day")),
                "scored_at": _now_iso(),
                "recorded_at": pred.get("recorded_at"),
            }
        )
        newly_scored += 1

    accuracy["scored"] = scored[-MAX_SCORED:]
    _write_json(ACCURACY_FILE, accuracy)

    store["predictions"] = remaining
    store["updated_at"] = _now_iso()
    _write_json(PENDING_FILE, store)

    if newly_scored:
        rebuild_accuracy_index()
    return newly_scored


def _backfill_scored_row(row: dict[str, Any]) -> bool:
    """Fill magnitude fields on legacy scored rows that predate return tracking."""
    if row.get("magnitude_hit") is not None and row.get("predicted_return_pct") is not None:
        return False

    predicted = str(row.get("predicted_direction", "flat")).lower()
    actual = str(row.get("actual_direction", "flat")).lower()
    horizon = str(row.get("horizon") or DEFAULT_HORIZON)
    conf = float(row.get("confidence", 0.5))
    hit = bool(row.get("hit"))

    predicted_return_pct = _predicted_return_value(row.get("predicted_return_pct"))
    if predicted_return_pct is None:
        from agent_fusion import estimate_return_from_bias

        predicted_return_pct = estimate_return_from_bias(predicted, confidence=conf)

    actual_return_pct = float(row.get("actual_return_pct", 0.0) or 0.0)
    magnitude_hit = _magnitude_hit(
        predicted_direction=predicted,
        actual_direction=actual,
        predicted_return_pct=predicted_return_pct,
        actual_return_pct=actual_return_pct,
        horizon=horizon,
    )
    row["predicted_return_pct"] = round(predicted_return_pct, 3)
    row["magnitude_hit"] = magnitude_hit
    row["magnitude_error_pct"] = round(abs(actual_return_pct - predicted_return_pct), 3)
    row.setdefault("regime_posture", "neutral")
    row.setdefault("event_day", False)
    row["brier_term"] = round((conf - (1.0 if hit else 0.0)) ** 2, 4)
    return True


def backfill_scored_magnitude(*, persist: bool = True) -> int:
    """Backfill magnitude metrics on historical scored predictions."""
    accuracy = _accuracy_store()
    scored: list[dict[str, Any]] = list(accuracy.get("scored") or [])
    updated = 0
    for row in scored:
        if isinstance(row, dict) and _backfill_scored_row(row):
            updated += 1
    if updated and persist:
        accuracy["scored"] = scored
        _write_json(ACCURACY_FILE, accuracy)
    return updated


def rebuild_accuracy_index() -> dict[str, Any]:
    """Aggregate per-agent accuracy from scored outcomes."""
    backfill_scored_magnitude()
    accuracy = _accuracy_store()
    scored: list[dict[str, Any]] = list(accuracy.get("scored") or [])
    agents: dict[str, dict[str, Any]] = {}

    for row in scored:
        aid = str(row.get("agent_id") or "")
        if not aid:
            continue
        bucket = agents.setdefault(
            aid,
            {
                "total": 0,
                "hits": 0,
                "weighted_hits": 0.0,
                "weighted_total": 0.0,
                "magnitude_total": 0,
                "magnitude_hits": 0,
                "magnitude_error_sum": 0.0,
                "brier_sum": 0.0,
                "by_horizon": {},
                "by_regime": {},
                "event_day_total": 0,
                "event_day_hits": 0,
            },
        )
        conf = float(row.get("confidence", 0.5))
        hit = bool(row.get("hit"))
        bucket["total"] += 1
        bucket["hits"] += 1 if hit else 0
        bucket["weighted_hits"] += conf if hit else 0.0
        bucket["weighted_total"] += conf
        bucket["brier_sum"] += float(row.get("brier_term", (conf - (1.0 if hit else 0.0)) ** 2))

        magnitude_hit = row.get("magnitude_hit")
        if magnitude_hit is not None:
            bucket["magnitude_total"] += 1
            bucket["magnitude_hits"] += 1 if magnitude_hit else 0
            err = row.get("magnitude_error_pct")
            if err is not None:
                bucket["magnitude_error_sum"] += float(err)

        if row.get("event_day"):
            bucket["event_day_total"] += 1
            bucket["event_day_hits"] += 1 if hit else 0

        horizon = str(row.get("horizon") or DEFAULT_HORIZON)
        hb = bucket["by_horizon"].setdefault(
            horizon,
            {"total": 0, "hits": 0, "magnitude_total": 0, "magnitude_hits": 0},
        )
        hb["total"] += 1
        hb["hits"] += 1 if hit else 0
        if magnitude_hit is not None:
            hb["magnitude_total"] += 1
            hb["magnitude_hits"] += 1 if magnitude_hit else 0

        regime = str(row.get("regime_posture") or "neutral")
        rb = bucket["by_regime"].setdefault(regime, {"total": 0, "hits": 0})
        rb["total"] += 1
        rb["hits"] += 1 if hit else 0

    leaderboard: list[dict[str, Any]] = []
    for aid, bucket in agents.items():
        total = int(bucket["total"])
        hits = int(bucket["hits"])
        w_total = float(bucket["weighted_total"])
        w_hits = float(bucket["weighted_hits"])
        accuracy_pct = round(hits / total * 100, 1) if total else None
        weighted_pct = round(w_hits / w_total * 100, 1) if w_total else None
        mag_total = int(bucket.get("magnitude_total", 0))
        mag_hits = int(bucket.get("magnitude_hits", 0))
        magnitude_pct = round(mag_hits / mag_total * 100, 1) if mag_total else None
        avg_magnitude_error_pct = (
            round(float(bucket.get("magnitude_error_sum", 0.0)) / mag_total, 2)
            if mag_total
            else None
        )
        combined_pct = None
        if weighted_pct is not None:
            if mag_total >= MIN_SAMPLES_FOR_MAGNITUDE and magnitude_pct is not None:
                combined_pct = round(
                    DIRECTION_WEIGHT * weighted_pct + MAGNITUDE_WEIGHT * magnitude_pct,
                    1,
                )
            else:
                combined_pct = weighted_pct
        brier_score = round(float(bucket.get("brier_sum", 0.0)) / total, 4) if total else None
        by_regime = {}
        for regime, rb in bucket.get("by_regime", {}).items():
            rt = int(rb.get("total", 0))
            rh = int(rb.get("hits", 0))
            by_regime[regime] = {
                "total": rt,
                "hits": rh,
                "accuracy_pct": round(rh / rt * 100, 1) if rt else None,
            }
        event_total = int(bucket.get("event_day_total", 0))
        event_hits = int(bucket.get("event_day_hits", 0))
        entry = {
            "agent_id": aid,
            "total_scored": total,
            "hits": hits,
            "accuracy_pct": accuracy_pct,
            "weighted_accuracy_pct": weighted_pct,
            "magnitude_accuracy_pct": magnitude_pct,
            "avg_magnitude_error_pct": avg_magnitude_error_pct,
            "combined_accuracy_pct": combined_pct,
            "magnitude_scored": mag_total,
            "brier_score": brier_score,
            "event_day_accuracy_pct": (
                round(event_hits / event_total * 100, 1) if event_total else None
            ),
            "weight_multiplier": (
                round(max(0.5, min(1.5, 0.5 + float(combined_pct) / 100.0)), 3)
                if total >= MIN_SAMPLES_FOR_WEIGHT and combined_pct is not None
                else 1.0
            ),
            "by_horizon": {
                h: {
                    "total": v["total"],
                    "hits": v["hits"],
                    "accuracy_pct": round(v["hits"] / v["total"] * 100, 1) if v["total"] else None,
                    "magnitude_total": v.get("magnitude_total", 0),
                    "magnitude_hits": v.get("magnitude_hits", 0),
                    "magnitude_accuracy_pct": (
                        round(v["magnitude_hits"] / v["magnitude_total"] * 100, 1)
                        if v.get("magnitude_total")
                        else None
                    ),
                }
                for h, v in bucket.get("by_horizon", {}).items()
            },
            "by_regime": by_regime,
        }
        bucket.update(entry)
        agents[aid] = bucket
        if total >= MIN_SAMPLES_FOR_WEIGHT and combined_pct is not None:
            leaderboard.append(entry)

    leaderboard.sort(
        key=lambda row: (row.get("combined_accuracy_pct") or 0, row.get("total_scored") or 0),
        reverse=True,
    )
    accuracy["agents"] = agents
    accuracy["leaderboard"] = leaderboard[:25]
    accuracy["pending_count"] = len((_load_json(PENDING_FILE) or {}).get("predictions", []))
    accuracy["updated_at"] = _now_iso()
    _write_json(ACCURACY_FILE, accuracy)
    try:
        from agent_fusion import export_walk_forward_weights

        export_walk_forward_weights()
    except Exception:
        pass
    return accuracy


def get_agent_accuracy(agent_id: str) -> dict[str, Any] | None:
    data = _accuracy_store()
    entry = (data.get("agents") or {}).get(agent_id)
    return entry if isinstance(entry, dict) else None


def pending_prediction_count(agent_id: str) -> int:
    store = _pending_store()
    aid = str(agent_id or "")
    return sum(1 for row in store.get("predictions", []) if str(row.get("agent_id")) == aid)


def agent_accuracy_label(agent_id: str) -> str:
    entry = get_agent_accuracy(agent_id)
    total = int(entry.get("total_scored") or entry.get("total") or 0) if entry else 0
    if total >= MIN_SAMPLES_FOR_WEIGHT and entry:
        pct = (
            entry.get("combined_accuracy_pct")
            or entry.get("weighted_accuracy_pct")
            or entry.get("accuracy_pct")
        )
        if pct is not None:
            mag = entry.get("magnitude_accuracy_pct")
            if mag is not None and int(entry.get("magnitude_scored") or 0) >= MIN_SAMPLES_FOR_MAGNITUDE:
                return f"{pct:.0f}% (mag {mag:.0f}%)"
            return f"{pct:.0f}%"
    pending = pending_prediction_count(agent_id)
    if pending:
        return f"{pending} tracking"
    if total:
        return f"{total} scored"
    return "—"


def agent_accuracy_weight(
    agent_id: str,
    *,
    store: dict[str, Any] | None = None,
    horizon: str = "24h",
    symbol: str = "",
    sector_hint: str = "",
) -> float:
    """Scale agent influence in fusion via walk-forward accuracy weights."""
    try:
        from agent_fusion import fusion_weight

        return fusion_weight(
            agent_id,
            horizon=horizon,
            symbol=symbol,
            sector_hint=sector_hint,
        )
    except Exception:
        data = store or _accuracy_store()
        entry = (data.get("agents") or {}).get(agent_id)
        if not isinstance(entry, dict):
            return 1.0
        total = int(entry.get("total_scored") or entry.get("total") or 0)
        if total < MIN_SAMPLES_FOR_WEIGHT:
            return 1.0
        pct = (
            entry.get("combined_accuracy_pct")
            or entry.get("weighted_accuracy_pct")
            or entry.get("accuracy_pct")
        )
        if pct is None:
            return 1.0
        return max(0.5, min(1.5, 0.5 + float(pct) / 100.0))


def accuracy_leaderboard(*, top_n: int = 10) -> list[dict[str, Any]]:
    data = _accuracy_store()
    board = list(data.get("leaderboard") or [])
    return board[:top_n]


def run_accuracy_cycle(*, cycle_id: str | None = None) -> dict[str, int]:
    """Record new predictions, score matured ones, rebuild index."""
    from price_history import record_prices

    recorded = record_cycle_predictions(cycle_id=cycle_id)
    record_prices(_quote_prices())
    scored = score_matured_predictions()
    if scored == 0:
        rebuild_accuracy_index()
    return {"recorded": recorded, "scored": scored}