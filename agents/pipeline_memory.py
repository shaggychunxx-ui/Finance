"""Pipeline run memory — load prior cycles and steer agent outputs at run start."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

_active_context: dict[str, Any] | None = None
_same_cycle_outputs: dict[str, dict[str, Any]] = {}


def get_active_pipeline_context() -> dict[str, Any]:
    return dict(_active_context or {})


def activate_pipeline_memory(context: dict[str, Any] | None) -> dict[str, Any]:
    global _active_context
    _active_context = dict(context or {})
    return _active_context


def clear_pipeline_memory() -> None:
    global _active_context
    _active_context = None


def begin_pipeline_memory_session() -> dict[str, Any]:
    """Load (or build) pipeline_run_context.json and activate it for this run."""
    from analysis_history import load_pipeline_run_context, write_pipeline_run_context

    global _same_cycle_outputs
    _same_cycle_outputs = {}
    try:
        from agents.market_data.yahoo import clear_yahoo_session_cache

        clear_yahoo_session_cache()
    except Exception:
        pass

    context = load_pipeline_run_context()
    if not isinstance(context, dict) or not context.get("agent_learning"):
        try:
            context = write_pipeline_run_context()
        except Exception:
            context = context if isinstance(context, dict) else {}
    return activate_pipeline_memory(context)


def end_pipeline_memory_session() -> None:
    global _same_cycle_outputs
    _same_cycle_outputs = {}
    try:
        from agents.market_data.yahoo import clear_yahoo_session_cache

        clear_yahoo_session_cache()
    except Exception:
        pass
    clear_pipeline_memory()


def register_same_cycle_agent_output(agent_id: str, data: dict[str, Any]) -> None:
    """Expose completed agent outputs to later agents in the same pipeline cycle."""
    global _same_cycle_outputs
    if isinstance(data, dict) and agent_id:
        _same_cycle_outputs[str(agent_id)] = data


def same_cycle_agent_outputs() -> dict[str, dict[str, Any]]:
    return dict(_same_cycle_outputs)


def _has_market_impact_signals(data: dict[str, Any]) -> bool:
    return any(
        isinstance(sig, dict) and str(sig.get("impact_scope") or "") == "market"
        for sig in (data.get("market_signals") or [])
    )


def _load_output_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _apply_disk_enhancements(target: dict[str, Any], disk: dict[str, Any]) -> None:
    """Layer E*TRADE / personality / learning patches from disk onto memory output."""
    for key in ("enhance_symbols",):
        if disk.get(key) is not None:
            target[key] = disk[key]

    disk_meta = disk.get("meta")
    if not isinstance(disk_meta, dict):
        return
    target_meta = target.setdefault("meta", {})
    if not isinstance(target_meta, dict):
        target_meta = {}
        target["meta"] = target_meta
    for key in (
        "personality",
        "learning",
        "etrade_enhancement_applied_at",
        "preferred_horizon",
        "pipeline_memory",
        "domain_constraints",
    ):
        if disk_meta.get(key) is not None:
            target_meta[key] = disk_meta[key]

    _merge_etrade_enhanced_nodes(target, disk)


def _merge_etrade_enhanced_nodes(target: Any, disk: Any) -> None:
    if isinstance(target, dict) and isinstance(disk, dict):
        if "etrade_enhanced" in disk and "etrade_enhanced" not in target:
            target["etrade_enhanced"] = disk["etrade_enhanced"]
            if disk.get("price") is not None and "price" not in target:
                target["price"] = disk["price"]
        for key, value in disk.items():
            if key in {"etrade_enhanced", "enhance_symbols", "quotes", "candidates"}:
                continue
            if key in target:
                _merge_etrade_enhanced_nodes(target[key], value)
    elif isinstance(target, list) and isinstance(disk, list):
        for index, disk_item in enumerate(disk):
            if index < len(target):
                _merge_etrade_enhanced_nodes(target[index], disk_item)


def merge_agent_output_for_restore(
    memory: dict[str, Any],
    disk: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer in-memory market-impact signals when disk looks like a stale overwrite."""
    if not disk:
        return dict(memory)

    mem_impact = _has_market_impact_signals(memory)
    disk_impact = _has_market_impact_signals(disk)
    if mem_impact and not disk_impact:
        merged = dict(memory)
        _apply_disk_enhancements(merged, disk)
        return merged
    if disk_impact or not mem_impact:
        return dict(disk)
    return dict(memory)


def sync_same_cycle_from_disk(
    sources: list[dict[str, str]] | None = None,
    *,
    agent_ids: set[str] | None = None,
) -> int:
    """Refresh in-memory outputs from disk (e.g. after E*TRADE quote enhancement)."""
    from app_paths import OUTPUT

    if sources is None:
        from agents.platform_catalog import active_agent_sources

        sources = active_agent_sources(check_remote=False)

    synced = 0
    for src in sources:
        aid = str(src.get("id") or "")
        if agent_ids is not None and aid not in agent_ids:
            continue
        disk = _load_output_json(OUTPUT / str(src.get("file") or ""))
        if not isinstance(disk, dict):
            continue
        memory = _same_cycle_outputs.get(aid)
        if isinstance(memory, dict):
            _same_cycle_outputs[aid] = merge_agent_output_for_restore(memory, disk)
        else:
            _same_cycle_outputs[aid] = disk
        synced += 1
    return synced


def restore_same_cycle_agent_outputs(
    sources: list[dict[str, str]] | None = None,
) -> int:
    """Persist in-memory same-cycle agent outputs back to disk.

    Guards against external processes overwriting output/*.json while a pipeline
    run is still in progress (e.g. GUI workers with stale agent code).
    """
    outputs = same_cycle_agent_outputs()
    if not outputs:
        return 0

    from app_paths import OUTPUT

    if sources is None:
        from agents.platform_catalog import active_agent_sources

        sources = active_agent_sources(check_remote=False)

    restored = 0
    for src in sources:
        aid = str(src.get("id") or "")
        memory = outputs.get(aid)
        if not isinstance(memory, dict):
            continue
        out_path = OUTPUT / str(src.get("file") or "")
        if not out_path.name.endswith(".json"):
            continue
        merged = merge_agent_output_for_restore(memory, _load_output_json(out_path))
        _same_cycle_outputs[aid] = merged
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        restored += 1
    return restored


def _live_quote_symbols(*, limit: int = 20) -> list[str]:
    try:
        from agents.enhancement import load_enhanced_quotes

        return sorted(load_enhanced_quotes().keys())[:limit]
    except Exception:
        return []


def memory_bundle_for_agent(agent_id: str) -> dict[str, Any]:
    """Per-agent slice of active pipeline memory for runners and BaseExpert."""
    ctx = get_active_pipeline_context()
    aid = str(agent_id or "")
    learning_row = (ctx.get("agent_learning") or {}).get(aid) or {}

    accuracy_rank: int | None = None
    for index, row in enumerate(ctx.get("accuracy_leaderboard") or [], start=1):
        if isinstance(row, dict) and row.get("agent_id") == aid:
            accuracy_rank = index
            break

    prior_runs = [row for row in (ctx.get("prior_pipeline_runs") or []) if isinstance(row, dict)]
    prior_hint: str | None = None
    if prior_runs:
        last = prior_runs[-1]
        agents_ok = int(last.get("agents_ok") or 0)
        agents_total = int(last.get("agents_total") or 0)
        cycle = str(last.get("cycle_id") or "?")
        prior_hint = f"Prior pipeline cycle {cycle}: {agents_ok}/{agents_total} agents succeeded."

    cross_votes: dict[str, Any] = {}
    contested: list[dict[str, Any]] = []
    try:
        from agent_disagreement import collect_agent_bias_votes, top_contested_symbols

        if _same_cycle_outputs:
            cross_votes = collect_agent_bias_votes(agent_outputs=_same_cycle_outputs, exclude_agent=aid)
        else:
            cross_votes = collect_agent_bias_votes(exclude_agent=aid)
        contested = top_contested_symbols(cross_votes, limit=8)
    except Exception:
        pass

    return {
        "agent_id": aid,
        "posture": learning_row.get("posture", "neutral"),
        "lessons": list(learning_row.get("lessons") or []),
        "avoid_symbols": [str(s).upper() for s in (learning_row.get("avoid_symbols") or [])],
        "trust_symbols": [str(s).upper() for s in (learning_row.get("trust_symbols") or [])],
        "bias_drift": float(learning_row.get("bias_drift") or 0.0),
        "fusion_multiplier": float(learning_row.get("fusion_multiplier") or 1.0),
        "preferred_horizon": str(learning_row.get("preferred_horizon") or "24h"),
        "accuracy_rank": accuracy_rank,
        "prior_runs_count": len(prior_runs),
        "prior_cycle_hint": prior_hint,
        "persistent_bullish_tickers": [
            str((s.get("symbol") if isinstance(s, dict) else s) or "").upper()
            for s in (ctx.get("persistent_bullish_tickers") or [])[:10]
            if (s.get("symbol") if isinstance(s, dict) else s)
        ],
        "live_quote_symbols": _live_quote_symbols(),
        "same_cycle_outputs": dict(_same_cycle_outputs),
        "cross_agent_votes": cross_votes,
        "contested_symbols": contested,
        "regime_history": list(ctx.get("regime_history") or [])[-3:],
        "accuracy_leaderboard_top": list(ctx.get("accuracy_leaderboard") or [])[:5],
        "total_pipeline_runs": int(ctx.get("total_pipeline_runs") or 0),
    }


def _primary_symbol(signal: dict[str, Any]) -> str:
    tickers = signal.get("tickers") or []
    if tickers:
        return str(tickers[0]).upper()
    symbol = signal.get("symbol")
    return str(symbol).upper() if symbol else ""


def _prepend_memory_recommendations(
    recommendations: list[Any],
    bundle: dict[str, Any],
    *,
    limit: int = 12,
) -> list[str]:
    out: list[str] = [str(row) for row in recommendations if row]
    for lesson in bundle.get("lessons") or []:
        note = f"[Memory] {lesson}"
        if note not in out:
            out.insert(0, note)
    hint = bundle.get("prior_cycle_hint")
    if hint:
        note = f"[Memory] {hint}"
        if note not in out:
            out.insert(0, note)
    rank = bundle.get("accuracy_rank")
    if rank is not None:
        note = f"[Memory] Accuracy rank #{rank} among tracked agents."
        if note not in out:
            out.append(note)
    return out[:limit]


def apply_pipeline_memory_to_result(
    data: dict[str, Any],
    agent_id: str,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Steer a freshly generated agent report using pipeline memory (no learning double-apply)."""
    if not isinstance(data, dict):
        return data

    bundle = bundle or memory_bundle_for_agent(agent_id)
    avoid = {str(s).upper() for s in (bundle.get("avoid_symbols") or [])}
    trust = {str(s).upper() for s in (bundle.get("trust_symbols") or [])}

    meta = data.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    meta["pipeline_memory"] = {
        "posture": bundle.get("posture"),
        "lessons": bundle.get("lessons"),
        "preferred_horizon": bundle.get("preferred_horizon"),
        "avoid_symbols": bundle.get("avoid_symbols"),
        "trust_symbols": bundle.get("trust_symbols"),
        "prior_runs_count": bundle.get("prior_runs_count"),
        "accuracy_rank": bundle.get("accuracy_rank"),
        "total_pipeline_runs": bundle.get("total_pipeline_runs"),
        "live_quote_symbols": bundle.get("live_quote_symbols"),
        "contested_symbols": bundle.get("contested_symbols"),
    }

    steered_signals: list[dict[str, Any]] = []
    for sig in data.get("market_signals") or []:
        if not isinstance(sig, dict):
            continue
        sym = _primary_symbol(sig)
        if sym and sym in avoid:
            continue
        row = dict(sig)
        if sym and sym in trust and "confidence" in row:
            try:
                row["confidence"] = round(min(0.99, float(row["confidence"]) * 1.06), 3)
            except (TypeError, ValueError):
                pass
        steered_signals.append(row)
    data["market_signals"] = steered_signals

    steered_opps: list[dict[str, Any]] = []
    for opp in data.get("trading_opportunities") or []:
        if not isinstance(opp, dict):
            continue
        sym = str(opp.get("symbol") or "").upper()
        if sym and sym in avoid:
            continue
        steered_opps.append(opp)
    if "trading_opportunities" in data:
        data["trading_opportunities"] = steered_opps

    data["recommendations"] = _prepend_memory_recommendations(
        list(data.get("recommendations") or []),
        bundle,
    )

    summary = str(meta.get("expert_summary") or data.get("expert_summary") or "").strip()
    lesson_preview = bundle.get("lessons") or []
    if lesson_preview and lesson_preview[0] not in summary:
        prefix = f"Memory: {lesson_preview[0]}"
        merged = f"{prefix} {summary}".strip() if summary else prefix
        if "expert_summary" in meta:
            meta["expert_summary"] = merged
        elif "expert_summary" in data:
            data["expert_summary"] = merged

    return data


def invoke_agent_runner(
    runner: Callable[..., Any],
    *,
    agent_id: str,
    output: Path,
) -> Any:
    """Execute an agent runner with pipeline memory and persist steered output."""
    bundle = memory_bundle_for_agent(agent_id)
    try:
        result = runner(output=output, pipeline_context=bundle)
    except TypeError:
        result = runner(output=output)

    if not isinstance(result, dict) and output.exists():
        try:
            loaded = json.loads(output.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                result = loaded
        except (OSError, json.JSONDecodeError):
            pass

    if isinstance(result, dict):
        result = apply_pipeline_memory_to_result(result, agent_id, bundle)
        try:
            from agent_constraints import apply_agent_constraints_to_result

            result = apply_agent_constraints_to_result(result, agent_id)
        except Exception:
            pass
        try:
            from agent_temperature import apply_temperature_to_result

            result = apply_temperature_to_result(
                result,
                agent_id,
                pipeline_context=bundle,
            )
        except Exception:
            pass
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result