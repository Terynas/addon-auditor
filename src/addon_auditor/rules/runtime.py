"""RUNTIME rule pack: findings from AuditorProbe SavedVariables.

The probe stores per-addon series sampled every ``interval`` seconds: ``mem`` (KB), ``cpu`` (ms of addon
code per second of wall time) and ``peakMs`` (worst single frame, profiler only), plus event fire
counts keyed by event (``EVENT`` or ``EVENT@unit``) and which keys each addon registered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.context import AuditContext
from ..core.finding import Emit, rule
from ..core.lua_ast import Node, parse

MIN_GROWTH_MINUTES = 2.0
FRAME_BUDGET_MS = 16.7


class ProbeError(ValueError):
    pass


def lua_value(node: Node) -> Any:
    """Convert a constant Lua expression (as written by SavedVariables) to Python."""
    k = node.kind
    if k == "String":
        return node.value
    if k == "Number":
        raw = str(node.value)
        if raw.lower().startswith("0x"):
            return int(raw, 16)
        num = float(raw)
        return int(num) if num.is_integer() and "." not in raw and "e" not in raw.lower() else num
    if k == "True":
        return True
    if k == "False":
        return False
    if k == "Nil":
        return None
    if k == "UnOp" and node.op == "-":
        v = lua_value(node.operand)
        return -v if isinstance(v, int | float) else None
    if k == "Paren":
        return lua_value(node.expr)
    if k == "Table":
        arr: list[Any] = []
        obj: dict[Any, Any] = {}
        for f in node.fields:
            if f.kind == "Item":
                arr.append(lua_value(f.value))
            else:
                key = f.key.id if f.key.kind == "Name" else lua_value(f.key)
                obj[key] = lua_value(f.value)
        if obj and arr:
            obj.update({i + 1: v for i, v in enumerate(arr)})
            return obj
        if obj and all(isinstance(key, int) for key in obj):
            return [obj[i] for i in sorted(obj)]
        return obj if obj else arr
    raise ProbeError(f"unsupported value {k} at line {node.line}")


def _parse_sv(path: Path) -> dict[str, Any]:
    src = path.read_text(encoding="utf-8", errors="replace")
    chunk, _ = parse(src)
    out: dict[str, Any] = {}
    block = chunk.body if chunk.body.kind == "Block" else chunk
    for st in block.body:
        if st.kind == "Assign":
            for tg, val in zip(st.targets, st.values, strict=False):
                if tg.kind == "Name":
                    out[tg.id] = lua_value(val)
    return out


def load_probe(path: Path, addon: str | None = None) -> dict[str, Any]:
    """Read ``AuditorProbe.lua`` SavedVariables; returns the latest session (optionally one addon)."""
    if not path.is_file():
        raise ProbeError(f"{path} not found")
    db = _parse_sv(path).get("AuditorProbeDB")
    if not isinstance(db, dict):
        raise ProbeError("AuditorProbeDB not found; run /probe start, /probe stop, then /reload")
    sessions = db.get("sessions") or []
    if isinstance(sessions, dict):
        sessions = [sessions[k] for k in sorted(sessions)]
    if not sessions:
        raise ProbeError("no probe sessions recorded yet")
    return {"source": str(path), "session": sessions[-1], "sessions": len(sessions), "addon": addon}


def _slope_per_min(times: list[float], values: list[float]) -> float:
    n = min(len(times), len(values))
    if n < 3:
        return 0.0
    t, v = times[-n:], values[-n:]
    mt, mv = sum(t) / n, sum(v) / n
    den = sum((x - mt) ** 2 for x in t)
    if den == 0:
        return 0.0
    return sum((x - mt) * (y - mv) for x, y in zip(t, v, strict=True)) / den * 60.0


def _addon_stats(session: dict[str, Any], name: str, a: dict[str, Any]) -> dict[str, Any]:
    mem = [float(x) for x in a.get("mem") or []]
    cpu = [float(x) for x in a.get("cpu") or []]
    times = [float(x) for x in session.get("times") or []]
    duration = float(session.get("duration") or (times[-1] if times else 0.0))
    keys = (session.get("registrations") or {}).get(name) or []
    events = session.get("events") or {}
    per_event = {k: int(events.get(k, 0)) for k in keys if events.get(k)}
    total = sum(per_event.values())
    return {
        "memory_kb_start": mem[0] if mem else None,
        "memory_kb_end": mem[-1] if mem else None,
        "memory_kb_peak": max(mem) if mem else None,
        "memory_growth_kb_per_min": round(_slope_per_min(times, mem), 1),
        "cpu_ms_per_sec_avg": round(sum(cpu) / len(cpu), 3) if cpu else None,
        "cpu_ms_per_sec_max": max(cpu) if cpu else None,
        "frame_peak_ms": a.get("peakMs"),
        "events_total": total,
        "events_per_sec": round(total / duration, 2) if duration > 0 else None,
        "top_events": sorted(per_event.items(), key=lambda kv: -kv[1])[:5],
    }


def summarize_probe(data: dict[str, Any]) -> dict[str, Any]:
    s = data["session"]
    addons = s.get("addons") or {}
    only = data.get("addon")
    stats = {name: _addon_stats(s, name, a) for name, a in addons.items() if not only or name == only}
    ranked = sorted(stats.items(), key=lambda kv: -(kv[1]["cpu_ms_per_sec_avg"] or 0))
    return {
        "source": data.get("source"),
        "sessions_stored": data.get("sessions"),
        "session": {k: s.get(k) for k in ("started", "stopped", "duration", "interval", "build", "interface",
                                          "cpuSource")},
        "addons": dict(ranked),
    }


def _stats(ctx: AuditContext) -> dict[str, Any] | None:
    cached = getattr(ctx, "_probe_stats", None)
    if cached is not None:
        return cached
    if ctx.probe is None:
        return None
    summary = summarize_probe({**ctx.probe, "addon": ctx.addon.name})
    st = summary["addons"].get(ctx.addon.name)
    out = {"stats": st, "session": summary["session"]}
    ctx._probe_stats = out  # type: ignore[attr-defined]
    return out


def _t(ctx: AuditContext, key: str) -> float:
    return float(ctx.config.thresholds[key])


@rule("RUN001", "runtime", "info", "Addon not loaded during the probe session",
      "AuditorProbe has no samples for this addon, so runtime rules cannot judge it.", scope="addon")
def addon_missing(ctx: AuditContext, emit: Emit) -> None:
    data = _stats(ctx)
    if data is not None and data["stats"] is None:
        emit(None, f"probe session has no data for {ctx.addon.name}",
             fix_hint="Enable the addon, /probe start, use its features for a few minutes, /probe stop, /reload.")


@rule("RUN002", "runtime", "warn", "High memory footprint",
      "Addon memory at the end of the probe session exceeds the threshold.", scope="addon")
def memory_high(ctx: AuditContext, emit: Emit) -> None:
    data = _stats(ctx)
    st = data and data["stats"]
    if not st or st["memory_kb_end"] is None:
        return
    limit = _t(ctx, "runtime_memory_kb_warn")
    if st["memory_kb_end"] > limit:
        emit(None, f"memory {st['memory_kb_end']:.0f} KB exceeds {limit:.0f} KB",
             fix_hint="Load data lazily, drop caches you can rebuild, avoid storing per-item tables "
                      "(pack into strings or arrays), and wipe() reused tables instead of recreating them.")


@rule("RUN003", "runtime", "warn", "Memory keeps growing",
      "Memory rises steadily over the session: garbage churn or an unbounded cache.", scope="addon",
      confidence="medium")
def memory_growth(ctx: AuditContext, emit: Emit) -> None:
    data = _stats(ctx)
    st = data and data["stats"]
    if not data or not st:
        return
    duration = float(data["session"].get("duration") or 0)
    rate = st["memory_growth_kb_per_min"]
    limit = _t(ctx, "runtime_memory_growth_kb_per_min_warn")
    if duration >= MIN_GROWTH_MINUTES * 60 and rate > limit:
        emit(None, f"memory grows {rate:.0f} KB/min over {duration / 60:.1f} min (threshold {limit:.0f})",
             fix_hint="Look for tables/closures/strings created in OnUpdate or frequent event handlers "
                      "(run `addon-auditor audit --category perf`) and caches without eviction.")


@rule("RUN004", "runtime", "warn", "High CPU usage",
      "Average addon CPU time per second of play exceeds the threshold.", scope="addon")
def cpu_high(ctx: AuditContext, emit: Emit) -> None:
    data = _stats(ctx)
    st = data and data["stats"]
    if not st or st["cpu_ms_per_sec_avg"] is None:
        return
    limit = _t(ctx, "runtime_cpu_ms_per_sec_warn")
    avg = st["cpu_ms_per_sec_avg"]
    if avg > limit:
        emit(None, f"average CPU {avg:.2f} ms/s (max {st['cpu_ms_per_sec_max']:.2f}) exceeds {limit:.2f} ms/s",
             severity="error" if avg > 5 * limit else None,
             fix_hint="Throttle OnUpdate, use RegisterUnitEvent, bucket bursty events with a short C_Timer, "
                      "cache results instead of re-querying APIs every update.")


@rule("RUN005", "runtime", "warn", "Frame hitch",
      "The addon's worst single-frame time exceeds one 60 FPS frame budget (profiler data).", scope="addon")
def frame_hitch(ctx: AuditContext, emit: Emit) -> None:
    data = _stats(ctx)
    st = data and data["stats"]
    if not st or not st["frame_peak_ms"]:
        return
    if float(st["frame_peak_ms"]) > FRAME_BUDGET_MS:
        emit(None, f"peak frame time {st['frame_peak_ms']:.1f} ms (> {FRAME_BUDGET_MS} ms budget)",
             fix_hint="Split large loops across frames (coroutine + C_Timer.After(0)), defer heavy scans "
                      "out of combat, and avoid full rebuilds on every event.")


@rule("RUN006", "runtime", "warn", "Event storm",
      "Events delivered to this addon per second exceed the threshold.", scope="addon", confidence="medium")
def event_storm(ctx: AuditContext, emit: Emit) -> None:
    data = _stats(ctx)
    st = data and data["stats"]
    if not st or not st["events_per_sec"]:
        return
    limit = _t(ctx, "runtime_events_per_sec_warn")
    if st["events_per_sec"] > limit:
        top = ", ".join(f"{k} ({v})" for k, v in st["top_events"])
        emit(None, f"{st['events_per_sec']:.0f} events/s exceeds {limit:.0f}; top: {top}",
             fix_hint="Unregister events you no longer need, use RegisterUnitEvent for UNIT_* events, and "
                      "coalesce bursts (e.g. BAG_UPDATE -> BAG_UPDATE_DELAYED).")
