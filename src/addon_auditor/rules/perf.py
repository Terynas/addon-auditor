"""PERF rule pack: per-frame cost, GC pressure, event fan-out and load-time work.

Hotness is stricter than :func:`._util.hot_functions`: an OnUpdate site is hot only when no throttle
(elapsed accumulator / ``GetTime`` comparison) or dirty-flag early return gates it, and an event-handler
site is hot only when the events reaching that branch (``if event == "X"``) fire many times per second.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from ..core.builtins import ALWAYS_KNOWN
from ..core.context import AuditContext, LuaFile
from ..core.finding import Emit, rule
from ..core.lua_ast import Node, call_name, dotted_name, enclosing_function, root_name, string_arg
from ._util import (
    EVENT_NAME,
    FREQUENT_EVENTS,
    function_table,
    iter_calls,
    method_target_name,
    registered_events,
    resolve_function,
    script_handlers,
    text_of,
)

# Events that can fire many times per second (per unit, per combat-log line, per cooldown tick).
HOT_EVENTS = FREQUENT_EVENTS & frozenset({
    "COMBAT_LOG_EVENT_UNFILTERED", "UNIT_AURA", "UNIT_HEALTH", "UNIT_HEALTH_FREQUENT", "UNIT_POWER_UPDATE",
    "UNIT_POWER_FREQUENT", "UNIT_ABSORB_AMOUNT_CHANGED", "UNIT_SPELLCAST_START", "UNIT_SPELLCAST_STOP",
    "UNIT_SPELLCAST_SUCCEEDED", "UNIT_THREAT_LIST_UPDATE", "UNIT_COMBAT", "ACTIONBAR_UPDATE_COOLDOWN",
    "ACTIONBAR_UPDATE_STATE", "SPELL_UPDATE_COOLDOWN", "SPELL_UPDATE_USABLE", "CHAT_MSG_ADDON",
})
# Per-unit events that are only hot while they are delivered for *every* unit in range.
_UNIT_SCOPED_HOT = frozenset({"UNIT_SPELLCAST_START", "UNIT_SPELLCAST_STOP", "UNIT_SPELLCAST_SUCCEEDED"})
LOAD_EVENTS = frozenset({"ADDON_LOADED", "PLAYER_LOGIN", "VARIABLES_LOADED", "PLAYER_ENTERING_WORLD"})
_LOOPS = ("While", "Repeat", "NumFor", "GenFor")
_TIME_CALLS = frozenset({"GetTime", "GetTimePreciseSec", "debugprofilestop", "time", "GetServerTime"})
_ELAPSED_PARAM = re.compile(r"^(elapsed|elapse|delta|dt)$", re.I)
_UNIT_TOKEN = re.compile(r"^(player|target|focus|pet|mouseover|vehicle|softenemy|softfriend|softinteract|"
                         r"(party|raid|boss|arena|nameplate|partypet|raidpet)\d+)$")
_REFRESH_NAME = re.compile(r"^(Refresh|Update|Redraw|Rebuild|Render|Repaint|Populate|Layout)")
_FORMAT_CALLS = frozenset({"string.format", "format", "strformat"})
_SEND_ADDON = frozenset({"C_ChatInfo.SendAddonMessage", "SendAddonMessage", "C_ChatInfo.SendAddonMessageLogged",
                         "SendAddonMessageLogged"})
_INSERT_CALLS = frozenset({"table.insert", "tinsert"})
_TRIM_CALLS = frozenset({"table.remove", "tremove", "wipe", "table.wipe"})
_POLL_APIS = {
    "GetMoney": "PLAYER_MONEY", "UnitHealth": "UNIT_HEALTH", "UnitHealthMax": "UNIT_MAXHEALTH",
    "UnitPower": "UNIT_POWER_UPDATE", "UnitPowerMax": "UNIT_MAXPOWER", "GetNumGroupMembers": "GROUP_ROSTER_UPDATE",
    "IsInGroup": "GROUP_ROSTER_UPDATE", "IsInRaid": "GROUP_ROSTER_UPDATE",
    "UnitAffectingCombat": "PLAYER_REGEN_DISABLED / PLAYER_REGEN_ENABLED",
    "InCombatLockdown": "PLAYER_REGEN_DISABLED / PLAYER_REGEN_ENABLED",
    "GetZoneText": "ZONE_CHANGED_NEW_AREA", "GetRealZoneText": "ZONE_CHANGED_NEW_AREA",
    "GetSubZoneText": "ZONE_CHANGED", "GetMinimapZoneText": "ZONE_CHANGED", "UnitLevel": "PLAYER_LEVEL_UP",
    "UnitXP": "PLAYER_XP_UPDATE", "IsResting": "PLAYER_UPDATE_RESTING", "IsMounted": "PLAYER_MOUNT_DISPLAY_CHANGED",
    "GetShapeshiftForm": "UPDATE_SHAPESHIFT_FORM", "C_Container.GetContainerNumFreeSlots": "BAG_UPDATE_DELAYED",
}
_DEBUG_CALL = re.compile(r"(^|[.:])(print|Print|Printf|AddMessage|Debug\w*|debug\w*|Dbg|Log|Trace)$")
_DEBUG_FLAG = re.compile(r"debug|verbose|trace|dbg", re.I)
_DATA_API = re.compile(r"^(Get|Is|Has|Find|Search|Request|Query)[A-Z]")
_CHEAP_NS = frozenset({"C_Timer", "C_AddOns", "C_CVar", "C_ChatInfo", "C_Console"})


# --------------------------------------------------------------------------- generic helpers


def _contains(outer: Node, inner: Node) -> bool:
    return outer is inner or any(a is outer for a in inner.ancestors())


def _direct_nodes(fn: Node) -> Iterator[Node]:
    """Nodes executed by ``fn`` itself: nested closures are yielded but not entered."""
    stack = [fn.body]
    while stack:
        n = stack.pop()
        yield n
        if n.kind == "Function":
            continue
        stack.extend(n.children())


def _returns(block: Node) -> bool:
    return any(st.kind == "Return" for st in block.body)


def _has_call(node: Node) -> bool:
    return any(n.kind in ("Call", "Method") for n in node.walk())


def _file_of(ctx: AuditContext, node: Node) -> LuaFile | None:
    roots = getattr(ctx, "_perf_roots", None)
    if roots is None:
        roots = {id(f.ast): f for f in ctx.parsed_files()}
        ctx._perf_roots = roots  # type: ignore[attr-defined]
    top = node
    while top.parent is not None:
        top = top.parent
    return roots.get(id(top))


def _in_loop_body(node: Node) -> Node | None:
    """Innermost loop (within the enclosing function) whose *repeated* part contains ``node``.

    Numeric-for bounds and generic-for iterator expressions run once, so they do not count."""
    prev = node
    for anc in node.ancestors():
        if anc.kind == "Function":
            return None
        if anc.kind in ("NumFor", "GenFor") and prev is anc.body:
            return anc
        if anc.kind in ("While", "Repeat"):
            return anc
        prev = anc
    return None


def _fn_name(fn: Node) -> str | None:
    if fn.a.get("fname"):
        return str(fn.fname)
    p = fn.parent
    if p is not None and p.kind == "Assign":
        for i, v in enumerate(p.values):
            if v is fn and i < len(p.targets):
                return dotted_name(p.targets[i])
    if p is not None and p.kind == "Local":
        for i, v in enumerate(p.values):
            if v is fn and i < len(p.names):
                return str(p.names[i].id)
    return None


def _describe(fn: Node, reason: str) -> str:
    """```Name`` (reason)` for named functions, ``the <reason>`` for anonymous ones."""
    name = _fn_name(fn)
    return f"`{name}` ({reason})" if name else f"the {reason}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _lines(nodes: list[Node], limit: int = 6) -> str:
    """``" (lines 3, 7)"`` when there is more than one line, else empty."""
    ls = sorted({n.line for n in nodes})
    if len(ls) < 2:
        return ""
    out = ", ".join(str(n) for n in ls[:limit])
    return f" (lines {out}{', ...' if len(ls) > limit else ''})"


def _alias_source(decl: Node) -> Node | None:
    """Name/Index a local was bound to (``local db = MyDB`` / later ``db = MyDB or {}``), if unique."""
    srcs: list[Node] = []
    p = decl.parent
    if p is not None and p.kind == "Local":
        idx = next((i for i, n in enumerate(p.names) if n is decl), -1)
        if 0 <= idx < len(p.values):
            srcs.append(p.values[idx])
    for ref in decl.a.get("refs", []):
        rp = ref.parent
        if rp is not None and rp.kind == "Assign" and ref in rp.targets:
            i = rp.targets.index(ref)
            if i < len(rp.values):
                srcs.append(rp.values[i])
    out = []
    for v in srcs:
        if v.kind == "BinOp" and v.op == "or":
            v = v.left
        if v.kind in ("Name", "Index"):
            out.append(v)
    return out[0] if len(out) == 1 else None


def _path(node: Node, depth: int = 0) -> str | None:
    """Dotted path of a Name/Index chain with local aliases resolved (``local list = db.history``)."""
    if depth > 4:
        return None
    if node.kind == "Name":
        decl = node.a.get("decl")
        if decl is None:
            return str(node.id)
        src = _alias_source(decl)
        if src is not None and src is not node:
            return _path(src, depth + 1) or str(node.id)
        return str(node.id)
    if node.kind == "Index" and node.key.kind == "String":
        base = _path(node.obj, depth)
        return f"{base}.{node.key.value}" if base else None
    return None


# --------------------------------------------------------------------------- throttle / gating


def _mentions_time(expr: Node, names: set[str]) -> bool:
    for x in expr.walk():
        if x.kind == "Call" and dotted_name(x.func) in _TIME_CALLS:
            return True
        if x.kind == "Name" and x.id in names:
            return True
        if x.kind == "Index" and dotted_name(x) in names:
            return True
    return False


def _time_names(fn: Node, seed: set[str]) -> set[str]:
    names = set(seed)
    for _ in range(2):
        for n in _direct_nodes(fn):
            if n.kind == "Assign":
                pairs = zip(n.targets, n.values, strict=False)
            elif n.kind == "Local":
                pairs = zip(n.names, n.values, strict=False)
            else:
                continue
            for tg, val in pairs:
                if _mentions_time(val, names):
                    nm = dotted_name(tg)
                    if nm:
                        names.add(nm)
    return names


def _time_cmp(cond: Node, names: set[str]) -> bool:
    for x in cond.walk():
        if x.kind == "BinOp" and x.op in ("<", ">", "<=", ">=") and (
                _mentions_time(x.left, names) or _mentions_time(x.right, names)):
            return True
    return False


def _elapsed_seed(fn: Node, onupdate: bool) -> set[str]:
    seed = {p.id for p in fn.params if _ELAPSED_PARAM.match(p.id)}
    if onupdate and len(fn.params) >= 2:
        seed.add(fn.params[1].id)
    return seed


def _time_names_cached(ctx: AuditContext, fn: Node, seed: set[str]) -> set[str]:
    cache = getattr(ctx, "_perf_tnames", None)
    if cache is None:
        cache = {}
        ctx._perf_tnames = cache  # type: ignore[attr-defined]
    if id(fn) not in cache:
        cache[id(fn)] = _time_names(fn, seed)
    return cache[id(fn)]


def _gated(node: Node, fn: Node, names: set[str]) -> bool:
    """``node`` only runs behind a time throttle or a dirty-flag early return inside ``fn``."""
    prev = node
    for anc in node.ancestors():
        if anc is fn:
            break
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if _contains(cond, prev):
                    break
                if _time_cmp(cond, names):
                    return True
                if body is prev:
                    break
        elif anc.kind == "Block":
            for st in anc.body:
                if st is prev:
                    break
                if st.kind == "If" and _returns(st.clauses[0][1]):
                    cond = st.clauses[0][0]
                    if _time_cmp(cond, names) or not _has_call(cond):
                        return True
        prev = anc
    return False


def _once_guarded(node: Node, fn: Node) -> bool:
    """Inside ``if not flag then`` / ``if x == nil then`` (pending / lazy-init pattern) within ``fn``."""
    prev = node
    for anc in node.ancestors():
        if anc is fn:
            break
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if body is prev:
                    if any(nm in (":UnregisterEvent", ":UnregisterAllEvents") or (n.kind == "Method" and
                                                                                  _clears_onupdate(n))
                           for n, nm in iter_calls(body)):
                        return True  # the branch switches itself off: runs once
                    for x in cond.walk():
                        if x.kind == "UnOp" and x.op == "not" and not _has_call(x.operand):
                            return True
                        if x.kind == "BinOp" and x.op == "==" and "Nil" in (x.left.kind, x.right.kind):
                            return True
                    break
        prev = anc
    return False


def _cond_events(cond: Node) -> set[str] | None:
    evs = set()
    for x in cond.walk():
        if x.kind == "BinOp" and x.op == "==":
            for side in (x.left, x.right):
                if side.kind == "String" and EVENT_NAME.match(str(side.value)):
                    evs.add(str(side.value))
    return evs or None


def _branch_events(node: Node, fn: Node) -> set[str] | None:
    """Events that can reach ``node`` judging by enclosing ``if event == "X"`` branches (None = any)."""
    out: set[str] | None = None
    prev = node
    for anc in node.ancestors():
        if anc is fn:
            break
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if body is prev:
                    ev = _cond_events(cond)
                    if ev is not None:
                        out = ev if out is None else out & ev
                    break
        prev = anc
    return out


# --------------------------------------------------------------------------- hot model


@dataclass
class _Hot:
    fn: Node
    reason: str
    kind: str  # "frame" (every frame) | "event" (frequent event)
    events: frozenset[str]
    seed: frozenset[str]


def _onupdate_handlers(ctx: AuditContext) -> list[tuple[LuaFile, Node, Node]]:
    """(file, SetScript call, handler Function) for every resolvable OnUpdate handler."""
    cache = getattr(ctx, "_perf_onupdate", None)
    if cache is None:
        cache = [(h.file, h.owner, h.func) for f in ctx.parsed_files()
                 for h in script_handlers(ctx, f, {"OnUpdate"}) if h.func is not None]
        ctx._perf_onupdate = cache  # type: ignore[attr-defined]
    return cache


def _event_fns(ctx: AuditContext) -> dict[int, tuple[Node, set[str], LuaFile | None]]:
    """id(Function) -> (Function, events it handles, file). OnEvent handlers get the events registered on
    the same frame in the same file (falling back to the file, then the addon)."""
    cache = getattr(ctx, "_perf_event_fns", None)
    if cache is not None:
        return cache
    regs = registered_events(ctx)
    by_target: dict[tuple[str, str | None], set[str]] = {}
    by_file: dict[str, set[str]] = {}
    for ev, sites in regs.items():
        for f, node in sites:
            by_target.setdefault((f.rel, method_target_name(node)), set()).add(ev)
            by_file.setdefault(f.rel, set()).add(ev)
    out: dict[int, tuple[Node, set[str], LuaFile | None]] = {}
    for f in ctx.parsed_files():
        for h in script_handlers(ctx, f, {"OnEvent"}):
            if h.func is None:
                continue
            tgt = method_target_name(h.owner)
            evs = by_target.get((f.rel, tgt)) or by_file.get(f.rel) or set(regs)
            out[id(h.func)] = (h.func, set(evs), f)
    for name, fn in function_table(ctx).items():
        last = re.split(r"[.:]", name)[-1]
        if EVENT_NAME.match(last) and last in regs:
            entry = out.setdefault(id(fn), (fn, set(), _file_of(ctx, fn)))
            entry[1].add(last)
    ctx._perf_event_fns = out  # type: ignore[attr-defined]
    return out


def _hot_events(ctx: AuditContext) -> frozenset[str]:
    """HOT_EVENTS minus per-unit events that are registered only through RegisterUnitEvent."""
    cache = getattr(ctx, "_perf_hot_events", None)
    if cache is None:
        regs = registered_events(ctx)
        unit_only = {ev for ev in _UNIT_SCOPED_HOT
                     if regs.get(ev) and all(call_name(n) == ":RegisterUnitEvent" for _f, n in regs[ev])}
        cache = HOT_EVENTS - unit_only
        ctx._perf_hot_events = cache  # type: ignore[attr-defined]
    return cache


def _unit_restricted(node: Node, fn: Node) -> bool:
    """``node`` only runs for fixed unit tokens (``if unit == "player"`` branch or a leading unit guard)."""
    prev = node
    for anc in node.ancestors():
        if anc is fn:
            break
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if body is prev:
                    if any(_unit_cmp(t, "==") for t in _and_terms(cond)):
                        return True
                    break
        elif anc.kind == "Block":
            for st in anc.body:
                if st is prev:
                    break
                if _guard_units(st) is not None:
                    return True
        prev = anc
    return False


def _hot_at(ctx: AuditContext, h: _Hot, node: Node) -> str | None:
    """Why ``node`` (directly inside ``h.fn``) runs hot, or None."""
    if h.kind == "frame":
        if _gated(node, h.fn, _time_names_cached(ctx, h.fn, set(h.seed))):
            return None
        return h.reason
    br = _branch_events(node, h.fn)
    evs = set(h.events) if br is None else (br & h.events if h.events else br)
    hot = evs & _hot_events(ctx)
    if hot & _UNIT_SCOPED_HOT and _unit_restricted(node, h.fn):
        hot -= _UNIT_SCOPED_HOT
    if not hot:
        return None
    return h.reason if br is None else f"handler branch for frequent event {sorted(hot)[0]}"


def _hot(ctx: AuditContext) -> dict[int, _Hot]:
    cache = getattr(ctx, "_perf_hot", None)
    if cache is not None:
        return cache
    hot: dict[int, _Hot] = {}
    for _f, _owner, fn in _onupdate_handlers(ctx):
        hot[id(fn)] = _Hot(fn, "OnUpdate handler (runs every frame)", "frame", frozenset(),
                           frozenset(_elapsed_seed(fn, True)))
    for fn, evs, _f in _event_fns(ctx).values():
        freq = evs & _hot_events(ctx)
        if freq and id(fn) not in hot:
            hot[id(fn)] = _Hot(fn, f"handler for frequent event {sorted(freq)[0]}", "event", frozenset(evs),
                               frozenset())
    ctx._perf_hot = hot  # type: ignore[attr-defined]
    # One level of direct callees, only from call sites that are themselves hot.
    for h in list(hot.values()):
        lf = _file_of(ctx, h.fn)
        if lf is None:
            continue
        for node in _direct_nodes(h.fn):
            if node.kind != "Call":
                continue
            reason = _hot_at(ctx, h, node)
            if reason is None:
                continue
            callee = resolve_function(ctx, lf, node.func)
            if callee is None or id(callee) in hot:
                continue
            evs = frozenset()
            if h.kind == "event":
                br = _branch_events(node, h.fn)
                evs = frozenset((br & h.events if h.events else br) if br is not None else h.events)
            hot[id(callee)] = _Hot(callee, f"called from {reason}", h.kind, evs,
                                   frozenset(_elapsed_seed(callee, False)))
    return hot


def _site_hot(ctx: AuditContext, node: Node) -> tuple[_Hot, str] | None:
    fn = enclosing_function(node)
    if fn is None:
        return None
    h = _hot(ctx).get(id(fn))
    if h is None:
        return None
    reason = _hot_at(ctx, h, node)
    return (h, reason) if reason else None


def _hot_in_file(ctx: AuditContext, lf: LuaFile) -> list[_Hot]:
    return [h for h in _hot(ctx).values() if _file_of(ctx, h.fn) is lf]


def _ticker_callbacks(ctx: AuditContext) -> dict[int, tuple[Node, float | None]]:
    """id(Function) -> (Function, interval seconds if constant) for C_Timer.NewTicker callbacks."""
    cache = getattr(ctx, "_perf_tickers", None)
    if cache is not None:
        return cache
    out: dict[int, tuple[Node, float | None]] = {}
    for f in ctx.parsed_files():
        assert f.ast is not None
        for node, name in iter_calls(f.ast):
            if name == "C_Timer.NewTicker" and len(node.args) >= 2:
                fn = resolve_function(ctx, f, node.args[1])
                if fn is not None:
                    out[id(fn)] = (fn, _number(node.args[0]))
    ctx._perf_tickers = out  # type: ignore[attr-defined]
    return out


def _number(node: Node) -> float | None:
    if node.kind == "Number":
        try:
            return float(node.value)
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- PERF001


def _throttled(ctx: AuditContext, fn: Node, seed: set[str], depth: int = 0) -> bool:
    names = _time_names(fn, seed)
    for n in _direct_nodes(fn):
        if n.kind == "If" and any(_time_cmp(c, names) for c, _ in n.clauses):
            return True
        if n.kind == "BinOp" and n.op in ("and", "or") and _time_cmp(n.left, names):
            return True
        if n.kind == "While" and _time_cmp(n.cond, names):
            return True
    for st in fn.body.body:
        if st.kind == "If" and _returns(st.clauses[0][1]) and not _has_call(st.clauses[0][0]):
            return True  # dirty-flag gate: `if not self.dirty then return end`
    # Delegation: handler forwards elapsed to a helper that does the throttling.
    if depth == 0 and seed:
        lf = _file_of(ctx, fn)
        for n in _direct_nodes(fn):
            if n.kind not in ("Call", "Method"):
                continue
            idx = next((i for i, a in enumerate(n.args) if a.kind == "Name" and a.id in seed), -1)
            if idx < 0:
                continue
            callee = resolve_function(ctx, lf, n.func) if (n.kind == "Call" and lf is not None) else None
            if callee is None:
                return True  # unresolvable helper gets elapsed: assume it throttles
            off = 1 if callee.params and callee.params[0].a.get("implicit") else 0
            if idx + off < len(callee.params) and _throttled(
                    ctx, callee, {callee.params[idx + off].id}, depth + 1):
                return True
    return False


def _clears_onupdate(n: Node) -> bool:
    return (n.kind == "Method" and n.name == "SetScript" and string_arg(n, 0) == "OnUpdate"
            and (len(n.args) < 2 or n.args[1].kind == "Nil"))


def _has_stop_path(lf: LuaFile, owner: Node, fn: Node) -> bool:
    for n in _direct_nodes(fn):
        if _clears_onupdate(n) or (n.kind == "Method" and n.name == "Hide"):
            return True
    target = method_target_name(owner)
    assert lf.ast is not None
    for n in lf.ast.walk():
        if n.kind != "Method":
            continue
        t = method_target_name(n)
        same = t == target or "self" in (t, target) or t is None or target is None
        if _clears_onupdate(n) and same:
            return True
        if n.name == "Hide" and t is not None and t == target and t != "self":
            return True
    return False


@rule("PERF001", "perf", "warn", "Unthrottled OnUpdate handler",
      "An OnUpdate script runs every rendered frame. Without an elapsed-time throttle or a way to stop it, "
      "it costs CPU 60-240 times per second for as long as the frame is shown.")
def onupdate_unthrottled(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    for f, owner, fn in _onupdate_handlers(ctx):
        if f is not lf:
            continue
        target = method_target_name(owner) or ""
        if re.search(r"anim", target.split(".")[-1], re.I):
            continue  # Animation/AnimationGroup OnUpdate only runs while the animation plays
        if not any(n.kind in ("Call", "Method") for n in _direct_nodes(fn)):
            continue  # call-free body (counter/arithmetic): negligible per-frame cost
        if _throttled(ctx, fn, _elapsed_seed(fn, True)) or _has_stop_path(lf, owner, fn):
            continue
        emit(owner.line, "OnUpdate handler has no elapsed-time throttle and is never cleared or hidden: it runs "
                         "every frame for the frame's lifetime.",
             end_line=fn.end_line,
             fix_hint="Accumulate elapsed and bail early: `self.t = (self.t or 0) + elapsed; if self.t < 0.1 then "
                      "return end; self.t = 0`. Better: drive it from events/C_Timer, and "
                      "`SetScript(\"OnUpdate\", nil)` when idle.")


# --------------------------------------------------------------------------- PERF002


def _skip_table(node: Node) -> bool:
    p = node.parent
    if p is None:
        return True
    if p.kind in ("Field", "Item"):
        return True  # counted with the outer constructor
    if p.kind == "BinOp" and p.op == "or" and p.right is node:
        return True  # `x = x or {}` lazy init
    if p.kind == "Call" and dotted_name(p.func) in ("error", "assert"):
        return True
    if p.kind == "Return":
        fn = enclosing_function(node)
        for a in p.ancestors():
            if a is fn:
                break
            if a.kind == "If":
                return True  # early-exit / error path
    return False


def _is_format(node: Node) -> bool:
    if node.kind == "Call":
        return dotted_name(node.func) in _FORMAT_CALLS
    return node.kind == "Method" and node.name == "format" and node.obj.kind in ("String", "Paren")


def _in_debug_call(node: Node, stop: Node) -> bool:
    for a in node.ancestors():
        if a is stop:
            return False
        if a.kind in ("Call", "Method") and _is_debug_call(a):
            return True
    return False


def _is_debug_call(n: Node) -> bool:
    name = call_name(n)
    return bool(name and _DEBUG_CALL.search(name))


def _timer_callback(node: Node) -> bool:
    p = node.parent
    return p is not None and p.kind == "Call" and (dotted_name(p.func) or "").startswith("C_Timer.")


@rule("PERF002", "perf", "warn", "Allocation in a hot path",
      "Tables, closures and strings created per frame or per frequent event become garbage immediately; the "
      "incremental GC then steals frame time and causes periodic hitches.", confidence="medium")
def hot_allocation(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    for h in _hot_in_file(ctx, lf):
        groups: dict[str, list[Node]] = {"table": [], "closure": [], "string": []}
        why = ""
        for n in _direct_nodes(h.fn):
            kind = None
            if n.kind == "Table" and not _skip_table(n):
                kind = "table"
            elif n.kind == "Function" and not _timer_callback(n):
                kind = "closure"
            elif ((n.kind == "BinOp" and n.op == ".." and not (n.parent and n.parent.kind == "BinOp"
                                                                and n.parent.op == ".."))
                  or _is_format(n)) and not _in_debug_call(n, h.fn):
                kind = "string"
            if kind is None or (kind != "string" and _once_guarded(n, h.fn)):
                continue
            reason = _hot_at(ctx, h, n)
            if reason is None:
                continue
            why = why or reason
            groups[kind].append(n)
        conf = "high" if h.kind == "frame" else "medium"
        where = _describe(h.fn, why)
        if groups["table"]:
            ns = groups["table"]
            emit(min(n.line for n in ns), f"{len(ns)} table constructor(s) allocate a new table every time "
                                          f"{where} runs{_lines(ns)}.",
                 confidence=conf,  # type: ignore[arg-type]
                 fix_hint="Hoist the table to a file-scope upvalue and `wipe()` it per call (or reuse a scratch "
                          "table); pass plain values instead of `{...}` packs.")
        if groups["closure"]:
            ns = groups["closure"]
            emit(min(n.line for n in ns), f"{len(ns)} closure(s) created every time {where} runs"
                                          f"{_lines(ns)}.",
                 confidence=conf,  # type: ignore[arg-type]
                 fix_hint="Define the function once at file scope (`local function OnX(...) end`) and reuse it; "
                          "pass state through arguments or upvalues.")
        if groups["string"]:
            ns = groups["string"]
            emit(min(n.line for n in ns), f"{len(ns)} string concatenation/format(s) build a new string every "
                                          f"time {where} runs{_lines(ns)}.",
                 severity="info", confidence=conf,  # type: ignore[arg-type]
                 fix_hint="Only rebuild the string when the underlying value changes (cache the last value), or "
                          "move formatting behind the throttle / into the refresh that actually updates the text.")


# --------------------------------------------------------------------------- PERF003

_REPEATED_SCRIPTS = frozenset({"OnUpdate", "OnShow", "OnEvent", "OnEnter", "OnSizeChanged"})


def _script_fn_map(ctx: AuditContext) -> dict[int, str]:
    cache = getattr(ctx, "_perf_scripts", None)
    if cache is None:
        cache = {}
        for f in ctx.parsed_files():
            for h in script_handlers(ctx, f, set(_REPEATED_SCRIPTS)):
                if h.func is not None:
                    cache.setdefault(id(h.func), h.script)
        ctx._perf_scripts = cache  # type: ignore[attr-defined]
    return cache


def _cache_guarded(call: Node, fn: Node) -> bool:
    p = call.parent
    if p is not None and p.kind == "BinOp" and p.op == "or" and p.right is call:
        return True  # frames[i] = frames[i] or CreateFrame(...)
    prev = call
    for anc in call.ancestors():
        if anc is fn:
            break
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if body is prev or _contains(cond, prev):
                    for x in cond.walk():
                        if x.kind == "UnOp" and x.op == "not":
                            return True
                        if x.kind == "BinOp" and x.op in ("==", "~=") and "Nil" in (x.left.kind, x.right.kind):
                            return True
                    break
        elif anc.kind == "Block":
            for st in anc.body:
                if st is prev:
                    break
                if st.kind == "If" and _returns(st.clauses[0][1]) and not _has_call(st.clauses[0][0]):
                    return True  # `if self.frame then return self.frame end`
        prev = anc
    return False


def _repeat_context(ctx: AuditContext, node: Node, fn: Node) -> str | None:
    script = _script_fn_map(ctx).get(id(fn))
    ev = _event_fns(ctx).get(id(fn))
    if ev is not None:
        br = _branch_events(node, fn)
        evs = br if br is not None else ev[1]
        if evs and evs <= LOAD_EVENTS:
            return None
        if evs:
            return f"event handler ({', '.join(sorted(evs)[:3])})"
    if script == "OnEvent":
        return None  # events unknown: be quiet
    if script is not None:
        return f"{script} handler"
    if id(fn) in _ticker_callbacks(ctx):
        return "C_Timer ticker callback"
    name = _fn_name(fn)
    if name:
        last = re.split(r"[.:]", name)[-1]
        if _REFRESH_NAME.match(last):
            return f"refresh function `{name}`"
    return None


@rule("PERF003", "perf", "warn", "CreateFrame in a repeatedly-run path",
      "Frames are never garbage collected. Creating them in an event handler, OnUpdate/OnShow script or "
      "refresh function leaks a frame (plus its regions and scripts) every time it runs.", confidence="medium")
def createframe_repeated(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    assert lf.ast is not None
    for node, name in iter_calls(lf.ast):
        if name != "CreateFrame":
            continue
        fn = enclosing_function(node)
        if fn is None or _cache_guarded(node, fn):
            continue
        where = _repeat_context(ctx, node, fn)
        if where is None:
            continue
        loop = _in_loop_body(node)
        extra = " inside a loop" if loop is not None else ""
        emit(node.line, f"CreateFrame{extra} in {where} with no reuse check: every run leaks new frames "
                        "(frames are never freed).",
             fix_hint="Create once and reuse: `self.rows[i] = self.rows[i] or CreateFrame(...)`, or acquire from "
                      "`CreateFramePool`/`CreateObjectPool` and `:Release` hidden rows.")


# --------------------------------------------------------------------------- PERF004


def _cancels_self(ctx: AuditContext, lf: LuaFile, call: Node) -> bool:
    if len(call.args) < 2:
        return False
    fn = resolve_function(ctx, lf, call.args[1])
    if fn is None:
        return True  # unknown callback: give benefit of the doubt
    if not fn.params:
        return False
    p = fn.params[0].id
    return any(n.kind == "Method" and n.name == "Cancel" and n.obj.kind == "Name" and n.obj.id == p
               for n in _direct_nodes(fn))


def _cancelled_names(ctx: AuditContext) -> set[str]:
    cache = getattr(ctx, "_perf_cancelled", None)
    if cache is None:
        cache = set()
        for f in ctx.parsed_files():
            assert f.ast is not None
            for n in f.ast.walk():
                if n.kind == "Method" and n.name == "Cancel":
                    p = _path(n.obj)
                    if p:
                        cache.add(p.split(".")[-1])
                elif n.kind == "Index" and n.key.kind == "String" and n.key.value == "Cancel":
                    p = _path(n.obj)
                    if p:
                        cache.add(p.split(".")[-1])
        ctx._perf_cancelled = cache  # type: ignore[attr-defined]
    return cache


def _stored_as(call: Node) -> tuple[str | None, bool]:
    """(target path the timer handle is stored in, handle escapes via return/argument)."""
    p = call.parent
    if p is None:
        return None, False
    if p.kind in ("Return", "Call", "Method", "Table", "Field", "Item"):
        return None, True
    if p.kind == "Assign":
        for i, v in enumerate(p.values):
            if v is call and i < len(p.targets):
                return dotted_name(p.targets[i]), False
    if p.kind == "Local":
        for i, v in enumerate(p.values):
            if v is call and i < len(p.names):
                decl = p.names[i]
                for ref in decl.a.get("refs", []):
                    rp = ref.parent
                    if rp is not None and rp.kind in ("Return", "Call", "Table", "Field", "Item", "Assign"):
                        if rp.kind != "Assign" or ref in rp.values:
                            return None, True
                return str(decl.id), False
    return None, False


@rule("PERF004", "perf", "warn", "Timer that cannot be cancelled / timer scheduled per frame",
      "A C_Timer ticker whose handle is dropped or never cancelled keeps firing for the whole session; "
      "C_Timer.After in a per-frame path allocates a closure and a timer every frame.", confidence="medium")
def timer_misuse(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    assert lf.ast is not None
    for node, name in iter_calls(lf.ast):
        if name == "C_Timer.NewTicker":
            if len(node.args) >= 3 or _cancels_self(ctx, lf, node):
                continue  # finite iterations, or the callback cancels itself
            target, escapes = _stored_as(node)
            if escapes:
                continue
            if node.parent is not None and node.parent.kind == "CallStmt":
                emit(node.line, "C_Timer.NewTicker result is discarded: the ticker runs forever and can never be "
                                "cancelled.",
                     fix_hint="Keep the handle (`self.ticker = C_Timer.NewTicker(...)`) and `self.ticker:Cancel()` "
                              "when the feature is disabled/hidden, or pass an iteration count.")
            elif target and target.split(".")[-1] not in _cancelled_names(ctx):
                emit(node.line, f"Ticker stored in `{target}` is never `:Cancel()`ed anywhere in the addon, so it "
                                "fires for the whole session.",
                     fix_hint=f"Call `{target}:Cancel()` (and nil it) when the work is no longer needed, e.g. on "
                              "hide/disable/combat end.")
        elif name == "C_Timer.NewTimer":
            if node.parent is not None and node.parent.kind == "CallStmt":
                emit(node.line, "C_Timer.NewTimer result is discarded; the handle exists only to allow `:Cancel()`.",
                     severity="info",
                     fix_hint="Use `C_Timer.After(delay, fn)` when you never cancel it (no handle object), or keep "
                              "the handle to cancel stale timers.")
        elif name == "C_Timer.After":
            hot = _site_hot(ctx, node)
            if hot is None or _once_guarded(node, hot[0].fn):
                continue
            emit(node.line, f"C_Timer.After in {_describe(hot[0].fn, hot[1])}: schedules a new timer (and usually a "
                            "closure) on every call.",
                 fix_hint="Schedule once and guard with a pending flag (`if not pending then pending = true; "
                          "C_Timer.After(...)`), or use a single ticker / the existing throttle.")


# --------------------------------------------------------------------------- PERF005


def _addon_name_vars(ctx: AuditContext) -> set[int]:
    """ids of Name decls bound to the addon name (``local addonName, ns = ...``)."""
    out: set[int] = set()
    for f in ctx.parsed_files():
        assert f.ast is not None
        for st in f.ast.body.body:
            if st.kind == "Local" and st.values and st.values[0].kind == "Vararg" and st.names:
                out.add(id(st.names[0]))
    return out


def _is_own_name(ctx: AuditContext, node: Node, name_vars: set[int]) -> bool:
    if node.kind == "String":
        return str(node.value) == ctx.addon.name
    if node.kind == "Name":
        decl = node.a.get("decl")
        return decl is not None and id(decl) in name_vars
    return False


@rule("PERF005", "perf", "info", "ADDON_LOADED never unregistered",
      "ADDON_LOADED fires once for every addon (including load-on-demand Blizzard modules opened later). A "
      "handler that only waits for its own addon keeps being dispatched for nothing.", scope="addon",
      confidence="medium")
def addon_loaded_kept(ctx: AuditContext, emit: Emit) -> None:
    sites = [s for s in registered_events(ctx).get("ADDON_LOADED", []) if call_name(s[1]) == ":RegisterEvent"]
    if not sites:
        return
    name_vars = _addon_name_vars(ctx)
    own_check = False
    for f in ctx.parsed_files():
        assert f.ast is not None
        for n, cname in iter_calls(f.ast):
            if cname == ":UnregisterAllEvents" or (
                    cname in (":UnregisterEvent", "UnregisterEvent") and "ADDON_LOADED" in text_of(n)):
                return
            if cname in ("IsAddOnLoaded", "C_AddOns.IsAddOnLoaded", "LoadAddOn", "C_AddOns.LoadAddOn",
                         "EventUtil.ContinueOnAddOnLoaded"):
                return  # watches other addons load: must keep listening
        for n in f.ast.walk():
            if n.kind != "BinOp" or n.op not in ("==", "~="):
                continue
            sides = (n.left, n.right)
            if any(_is_own_name(ctx, s, name_vars) for s in sides):
                own_check = True
            elif any(s.kind == "String" and not EVENT_NAME.match(str(s.value)) and str(s.value)[:1].isupper()
                     and re.match(r"^[A-Za-z][\w-]+$", str(s.value)) and "_" in str(s.value) for s in sides):
                return  # e.g. `name == "Blizzard_AuctionHouseUI"`: handler serves other addons too
    if not own_check:
        return
    f, node = sites[0]
    emit(node.line, "ADDON_LOADED is registered and the handler checks for this addon's name, but it is never "
                    "unregistered: it keeps firing for every addon loaded afterwards.",
         file=f.rel,
         fix_hint="After your init runs, call `self:UnregisterEvent(\"ADDON_LOADED\")` (or use "
                  "`EventUtil.ContinueOnAddOnLoaded(addonName, Init)`).")


# --------------------------------------------------------------------------- PERF006


def _and_terms(cond: Node) -> list[Node]:
    if cond.kind == "Paren":
        return _and_terms(cond.expr)
    if cond.kind == "BinOp" and cond.op == "and":
        return _and_terms(cond.left) + _and_terms(cond.right)
    return [cond]


def _or_terms(cond: Node) -> list[Node]:
    if cond.kind == "Paren":
        return _or_terms(cond.expr)
    if cond.kind == "BinOp" and cond.op == "or":
        return _or_terms(cond.left) + _or_terms(cond.right)
    return [cond]


def _unit_cmp(term: Node, op: str) -> tuple[str, str] | None:
    """``unit <op> "player"`` -> (var name, token)."""
    if term.kind == "Paren":
        return _unit_cmp(term.expr, op)
    if term.kind == "UnOp" and term.op == "not" and op == "~=":
        return _unit_cmp(term.operand, "==")
    if term.kind != "BinOp" or term.op != op:
        return None
    for a, b in ((term.left, term.right), (term.right, term.left)):
        if a.kind == "Name" and not a.a.get("is_global") and b.kind == "String" and _UNIT_TOKEN.match(str(b.value)):
            return str(a.id), str(b.value)
    return None


def _guard_units(n: Node) -> set[str] | None:
    """``if unit ~= "a" [and unit ~= "b"] then return end`` -> {"a", "b"}."""
    if n.kind != "If" or len(n.clauses) != 1 or "orelse" in n.a:
        return None
    cond, body = n.clauses[0]
    if len(body.body) != 1 or body.body[0].kind != "Return":
        return None
    cmps = [_unit_cmp(t, "~=") for t in _and_terms(cond)]
    if not cmps or not all(cmps) or len({c[0] for c in cmps if c}) != 1:
        return None
    return {c[1] for c in cmps if c}


def _leading_guard(block: Node) -> Node | None:
    """First statement of ``block`` after plain locals, if it is a unit guard."""
    for st in block.body:
        if st.kind == "Local" and not any(_has_call(v) for v in st.values):
            continue
        return st if _guard_units(st) is not None else None
    return None


def _unit_filters(fn: Node) -> dict[str | None, set[str]]:
    """Units a handler restricts itself to, keyed by event branch (None = all events reaching the guard).

    Recognises leading early-return guards (``if unit ~= "player" then return end``) at the top of the handler
    or of an event branch, and event branches that also test the unit
    (``if event == "UNIT_AURA" and unit == "target" then``). ``"!EVENT"`` marks a branch with no unit filter."""
    out: dict[str | None, set[str]] = {}
    unrestricted: set[str] = set()
    top = _leading_guard(fn.body)
    if top is not None:
        out[None] = set(_guard_units(top) or ())
    for n in _direct_nodes(fn):
        if n.kind != "If":
            continue
        for c, body in n.clauses:
            evs = _cond_events(c)
            if not evs:
                continue
            units: set[str] = set()
            for t in _and_terms(c):
                ors = [_unit_cmp(o, "==") for o in _or_terms(t)]
                if ors and all(ors):
                    units.update(o[1] for o in ors if o)
            guard = _leading_guard(body)
            if not units and guard is not None:
                units = set(_guard_units(guard) or ())
            for ev in evs:
                if units:
                    out.setdefault(ev, set()).update(units)
                else:
                    unrestricted.add(ev)
    for ev in unrestricted:
        out.pop(ev, None)
        out.setdefault("!" + ev, set())
    return out


@rule("PERF006", "perf", "warn", "UNIT_* event filtered in Lua instead of RegisterUnitEvent",
      "RegisterEvent(\"UNIT_HEALTH\") wakes your handler for every unit in range (party, raid, nameplates). If "
      "the handler only cares about one or two units, RegisterUnitEvent filters in C before Lua runs.",
      scope="addon", confidence="medium")
def unit_event_filter(ctx: AuditContext, emit: Emit) -> None:
    if any("AceEvent-3.0" in f.src for f in ctx.lua_files(loaded_only=False)):
        return  # AceEvent has no unit-event registration
    regs = registered_events(ctx)
    ev_fns = _event_fns(ctx)
    for ev, sites in regs.items():
        if not ev.startswith("UNIT_"):
            continue
        if any(call_name(n) == ":RegisterUnitEvent" for _f, n in sites):
            continue
        handlers = [fn for fn, evs, _lf in ev_fns.values() if ev in evs]
        if not handlers:
            continue
        units: set[str] = set()
        ok = True
        for fn in handlers:
            filt = _unit_filters(fn)
            if None in filt:
                got = filt[None]
            elif "!" + ev in filt:
                ok = False
                break
            else:
                got = filt.get(ev)
            if not got:
                ok = False
                break
            units |= got
        if not ok or not units or len(units) > 2:
            continue
        unit_args = ", ".join(f'"{u}"' for u in sorted(units))
        for f, node in sites:
            if call_name(node) != ":RegisterEvent":
                continue
            emit(node.line, f"{ev} is registered for all units but the handler ignores everything except "
                            f"{unit_args}.",
                 file=f.rel,
                 fix_hint=f"`{method_target_name(node) or 'frame'}:RegisterUnitEvent(\"{ev}\", {unit_args})` and "
                          "drop the Lua-side unit check.")


# --------------------------------------------------------------------------- PERF007


@rule("PERF007", "perf", "info", "COMBAT_LOG_EVENT_UNFILTERED handler",
      "CLEU fires for every combat-log line in range: thousands per minute in raids. Any work before the "
      "subevent filter, or any allocation, is multiplied by that rate.", confidence="high")
def cleu(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    for f, node in registered_events(ctx).get("COMBAT_LOG_EVENT_UNFILTERED", []):
        if f is not lf:
            continue
        emit(node.line, "Registers COMBAT_LOG_EVENT_UNFILTERED, the highest-volume event in the client.",
             tags=["symbol:COMBAT_LOG_EVENT_UNFILTERED"],
             fix_hint="Call `CombatLogGetCurrentEventInfo()` once, return immediately unless the subevent/GUID is "
                      "one you need, never allocate per event, and unregister outside combat/instances.")


# --------------------------------------------------------------------------- PERF008


def _client_global(ctx: AuditContext, name: str) -> bool:
    if name in ctx.addon_globals or name in ctx.addon.saved_variables or name in ctx.xml_global_names:
        return False
    if name in ALWAYS_KNOWN:
        return True
    return any(ctx.api.global_in(name).values())


@rule("PERF008", "perf", "info", "Repeated global lookups in a hot path",
      "Every global access is a hash lookup in _G. In code that runs every frame or per frequent event, "
      "repeated lookups of the same API add up; a file-scope local turns them into upvalue reads.",
      confidence="low")
def hot_globals(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    for h in _hot_in_file(ctx, lf):
        counts: dict[str, int] = {}
        looped: set[str] = set()
        first: dict[str, int] = {}
        why = ""
        for n in _direct_nodes(h.fn):
            if n.kind != "Name" or not n.a.get("is_global") or n.a.get("is_write"):
                continue
            if not _client_global(ctx, n.id):
                continue
            reason = _hot_at(ctx, h, n)
            if reason is None:
                continue
            why = why or reason
            key = n.id
            p = n.parent
            if p is not None and p.kind == "Index" and p.obj is n and p.key.kind == "String":
                key = f"{n.id}.{p.key.value}"
            counts[key] = counts.get(key, 0) + 1
            first.setdefault(key, n.line)
            if _in_loop_body(n) is not None:
                looped.add(key)
        names = sorted((k for k, c in counts.items() if c >= 3 or k in looped), key=lambda k: first[k])
        if not names:
            continue
        shown = ", ".join(names[:8]) + (", ..." if len(names) > 8 else "")
        local_names = ", ".join(k.replace(".", "_") if "." in k else k for k in names[:3])
        emit(first[names[0]], f"{_cap(_describe(h.fn, why))} looks up these globals repeatedly or inside a loop: "
                              f"{shown}.",
             fix_hint=f"Cache them at the top of the file: `local {local_names} = "
                      f"{', '.join(names[:3])}`.")


# --------------------------------------------------------------------------- PERF009


def _call_names_in(node: Node) -> list[tuple[Node, str]]:
    return [(n, nm) for n, nm in iter_calls(node) if not nm.startswith(":")]


def _is_data_api(ctx: AuditContext, call: Node, name: str) -> bool:
    r = root_name(call.func) if call.kind == "Call" else None
    if r is None or not r.a.get("is_global"):
        return False
    parts = name.split(".")
    if parts[0] in _CHEAP_NS:
        return False
    if len(parts) == 2 and parts[0].startswith("C_"):
        return bool(_DATA_API.match(parts[1])) and any(ctx.api.namespace_known(parts[0]).values())
    return len(parts) == 1 and bool(_DATA_API.match(name)) and _client_global(ctx, name)


@rule("PERF009", "perf", "warn", "Heavy loop at file load",
      "Code at file scope runs while the loading screen is up, before most game data is cached. Iterating game "
      "data or creating many frames there lengthens every login and /reload.", confidence="medium")
def load_time_work(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    assert lf.ast is not None
    for loop in lf.ast.walk():
        if loop.kind not in _LOOPS or any(a.kind == "Function" or a.kind in _LOOPS for a in loop.ancestors()):
            continue
        calls = _call_names_in(loop)
        data = [nm for n, nm in calls if _is_data_api(ctx, n, nm)]
        frames = any(nm == "CreateFrame" for _n, nm in calls)
        bound = _number(loop.stop) if loop.kind == "NumFor" else None
        stop_call = None
        if loop.kind == "NumFor" and loop.stop.kind == "Call":
            sn = dotted_name(loop.stop.func) or ""
            if re.search(r"(^|\.)GetNum\w+$", sn):
                stop_call = sn
        reason = None
        if stop_call and data:
            reason = f"iterates `{stop_call}()` calling {', '.join(sorted(set(data))[:3])}"
        elif bound is not None and bound >= 1000 and data:
            reason = f"runs {int(bound)} iterations calling {', '.join(sorted(set(data))[:3])}"
        elif bound is not None and bound >= 100 and frames:
            reason = f"creates {int(bound)}+ frames"
        if reason is None:
            continue
        emit(loop.line, f"File-scope loop {reason} while the addon loads.", end_line=loop.end_line,
             fix_hint="Defer it to `PLAYER_LOGIN` or to first use (lazy init), spread it with `C_Timer.After`, "
                      "or create frames on demand from a pool.")


# --------------------------------------------------------------------------- PERF010


def _sv_aliases(ctx: AuditContext) -> set[str]:
    cache = getattr(ctx, "_perf_sv_alias", None)
    if cache is not None:
        return cache
    aliases = set(ctx.addon.saved_variables)
    if aliases:
        # Shared aliases only (`ns.db = MyDB`, `self.db = MyDB.char`); locals resolve through _path().
        for _ in range(2):
            for f in ctx.parsed_files():
                assert f.ast is not None
                for n in f.ast.walk():
                    if n.kind != "Assign":
                        continue
                    for tg, v in zip(n.targets, n.values, strict=False):
                        if tg.kind == "Name" and not tg.a.get("is_global"):
                            continue
                        if v.kind == "BinOp" and v.op == "or":
                            v = v.left
                        vp = _path(v) if v.kind in ("Name", "Index") else None
                        tp = _path(tg)
                        if vp and tp and tp not in aliases and _sv_rooted(vp, aliases):
                            aliases.add(tp)
    ctx._perf_sv_alias = aliases  # type: ignore[attr-defined]
    return aliases


def _sv_rooted(path: str, aliases: set[str]) -> bool:
    parts = path.split(".")
    return any(".".join(parts[:i]) in aliases for i in range(1, len(parts) + 1))


def _trimmed_segments(ctx: AuditContext) -> set[str]:
    cache = getattr(ctx, "_perf_trimmed", None)
    if cache is not None:
        return cache
    out: set[str] = set()

    def add(node: Node) -> None:
        p = _path(node)
        if p:
            out.add(p.split(".")[-1])

    for f in ctx.parsed_files():
        assert f.ast is not None
        for n in f.ast.walk():
            if n.kind == "Call" and dotted_name(n.func) in _TRIM_CALLS and n.args:
                add(n.args[0])
            elif n.kind == "BinOp" and n.op in (">", ">=", "<", "<="):
                for side in (n.left, n.right):
                    if side.kind == "UnOp" and side.op == "#":
                        add(side.operand)
            elif n.kind == "Assign":
                for i, tg in enumerate(n.targets):
                    v = n.values[i] if i < len(n.values) else None
                    if v is not None and v.kind == "Table" and not v.fields:
                        add(tg)  # reset: X.history = {}
                    if v is not None and v.kind == "Nil" and tg.kind == "Index" and tg.key.kind != "String":
                        add(tg.obj)  # X[k] = nil
    ctx._perf_trimmed = out  # type: ignore[attr-defined]
    return out


def _dedup_guarded(node: Node) -> bool:
    fn = enclosing_function(node)
    for anc in node.ancestors():
        if anc is fn:
            break
        if anc.kind == "If":
            for cond, _b in anc.clauses:
                if any((x.kind == "UnOp" and x.op == "not") or
                       (x.kind == "Call" and dotted_name(x.func) == "tContains") for x in cond.walk()):
                    return True
    return False


@rule("PERF010", "perf", "warn", "SavedVariables list grows without bound",
      "Everything in SavedVariables is parsed at login and serialized at logout. A list that is appended to "
      "every session and never trimmed makes both slower forever and bloats memory.", scope="addon",
      confidence="medium")
def sv_unbounded(ctx: AuditContext, emit: Emit) -> None:
    aliases = _sv_aliases(ctx)
    if not ctx.addon.saved_variables:
        return
    trimmed = _trimmed_segments(ctx)
    seen: set[str] = set()
    for f in ctx.parsed_files():
        assert f.ast is not None
        for n in f.ast.walk():
            container: Node | None = None
            if n.kind == "Call" and dotted_name(n.func) in _INSERT_CALLS and len(n.args) >= 2:
                container = n.args[0]
            elif n.kind == "Assign" and len(n.targets) == 1 and n.targets[0].kind == "Index":
                tg = n.targets[0]
                k = tg.key
                if k.kind == "BinOp" and k.op == "+" and k.left.kind == "UnOp" and k.left.op == "#":
                    if _path(k.left.operand) == _path(tg.obj):
                        container = tg.obj
            if container is None:
                continue
            path = _path(container)
            if not path or not _sv_rooted(path, aliases) or path in seen:
                continue
            if path.split(".")[-1] in trimmed or _dedup_guarded(n):
                continue
            seen.add(path)
            emit(n.line, f"Appends to SavedVariables table `{path}` but nothing in the addon ever trims it "
                         "(no table.remove / wipe / size check).",
                 file=f.rel,
                 fix_hint=f"Cap it after inserting: `while #{path} > 200 do table.remove({path}, 1) end` (or keep "
                          "a ring buffer / prune old entries at PLAYER_LOGIN).")


# --------------------------------------------------------------------------- PERF011


def _debug_guarded(node: Node) -> bool:
    for anc in node.ancestors():
        if anc.kind == "If" and any(_DEBUG_FLAG.search(text_of(c)) for c, _b in anc.clauses):
            return True
        if anc.kind == "BinOp" and anc.op == "and" and _DEBUG_FLAG.search(text_of(anc.left)):
            return True
    return False


@rule("PERF011", "perf", "info", "Debug message formatted in a hot path",
      "Arguments are evaluated before the call: `Debug(\"hp \" .. hp)` builds the string every frame even when "
      "the debug wrapper discards it.", confidence="medium")
def hot_debug_format(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    for h in _hot_in_file(ctx, lf):
        for n in _direct_nodes(h.fn):
            if n.kind not in ("Call", "Method") or not _is_debug_call(n):
                continue
            if not any(x.kind == "BinOp" and x.op == ".." or _is_format(x) for a in n.args for x in a.walk()):
                continue
            reason = _hot_at(ctx, h, n)
            if reason is None or _debug_guarded(n):
                continue
            emit(n.line, f"Log/debug call in {_describe(h.fn, reason)} formats its message on every call.",
                 fix_hint="Wrap it: `if MyAddon.debug then Debug(...) end`, or pass raw values and format inside "
                          "the debug function after the flag check.")


# --------------------------------------------------------------------------- PERF012


@rule("PERF012", "perf", "info", "Polling state that has an event",
      "Re-querying a value from OnUpdate or a ticker and comparing it with a cached copy costs CPU every "
      "tick; the client already announces the change with an event.", confidence="low")
def polling(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    fns: list[tuple[Node, str]] = [(fn, "OnUpdate handler") for f, _o, fn in _onupdate_handlers(ctx) if f is lf]
    fns += [(fn, "ticker callback") for fn, _i in _ticker_callbacks(ctx).values() if _file_of(ctx, fn) is lf]
    for fn, where in fns:
        cmp_text: list[Node] = [n for n in _direct_nodes(fn) if n.kind == "BinOp" and n.op in ("==", "~=")]
        if not cmp_text:
            continue
        for n in _direct_nodes(fn):
            if n.kind != "Call":
                continue
            api = dotted_name(n.func)
            if api not in _POLL_APIS:
                continue
            names = {api}
            p = n.parent
            while p is not None and p.kind in ("BinOp", "UnOp", "Paren") and p.a.get("op") not in ("==", "~="):
                p = p.parent
            if p is not None and p.kind in ("Local", "Assign"):
                targets = p.names if p.kind == "Local" else p.targets
                vals = list(p.values)
                idx = next((i for i, v in enumerate(vals) if _contains(v, n)), -1)
                if 0 <= idx < len(targets):
                    t = dotted_name(targets[idx])
                    if t:
                        names.add(t)
            if not any(_contains(c, n) or any(
                    (x.kind == "Name" and x.id in names) or (x.kind == "Index" and dotted_name(x) in names)
                    for x in c.walk()) for c in cmp_text):
                continue
            emit(n.line, f"{where} polls `{api}()` and compares it with a cached value; "
                         f"{_POLL_APIS[api]} reports that change.",
                 fix_hint=f"Register `{_POLL_APIS[api].split(' ')[0]}` and update from the event handler instead "
                          "of polling.")
            break


# --------------------------------------------------------------------------- PERF013


@rule("PERF013", "perf", "warn", "Addon message sent per frame / in a loop",
      "SendAddonMessage is rate limited by the server (small burst, slow refill). Sending from OnUpdate, a fast "
      "ticker or a loop drops messages and can get the player disconnected for flooding.", confidence="medium")
def addon_message_flood(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    assert lf.ast is not None
    tickers = _ticker_callbacks(ctx)
    for node, name in iter_calls(lf.ast):
        if name not in _SEND_ADDON:
            continue
        fn = enclosing_function(node)
        where = None
        hot = _site_hot(ctx, node)
        if hot is not None and hot[0].kind == "frame":
            where = _describe(hot[0].fn, hot[1])
        elif fn is not None and id(fn) in tickers and tickers[id(fn)][1] is not None and tickers[id(fn)][1] < 1:
            where = f"a {tickers[id(fn)][1]}s ticker"
        elif _in_loop_body(node) is not None:
            where = "a loop"
        if where is None:
            continue
        emit(node.line, f"{name} inside {where}: bursts exceed the server's addon-message throttle.",
             fix_hint="Batch the payload into one message, send through ChatThrottleLib / AceComm, or queue sends "
                      "and drain at most a few per second from a throttled timer.")
