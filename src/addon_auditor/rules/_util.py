"""Shared analyses for rule packs.

Terminology:
- *hot* function: runs every frame (OnUpdate handler, or a function it calls directly).
- *warm* function: runs per event / script callback (OnEvent, event-method handlers, C_Timer callbacks,
  OnShow/OnClick etc.). Allocation there is fine unless the event is frequent.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from ..core.context import AuditContext, LuaFile
from ..core.lua_ast import Node, call_name, dotted_name, root_name, string_arg

EVENT_NAME = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")

# Events that fire very often; handlers for these are treated as hot.
FREQUENT_EVENTS = frozenset({
    "COMBAT_LOG_EVENT_UNFILTERED", "UNIT_AURA", "UNIT_HEALTH", "UNIT_POWER_UPDATE", "UNIT_POWER_FREQUENT",
    "UNIT_HEALTH_FREQUENT", "UNIT_ABSORB_AMOUNT_CHANGED", "UNIT_SPELLCAST_START", "UNIT_SPELLCAST_STOP",
    "UNIT_SPELLCAST_SUCCEEDED", "UNIT_THREAT_LIST_UPDATE", "UNIT_COMBAT", "BAG_UPDATE", "BAG_UPDATE_DELAYED",
    "ACTIONBAR_UPDATE_COOLDOWN", "ACTIONBAR_UPDATE_STATE", "SPELL_UPDATE_COOLDOWN", "SPELL_UPDATE_USABLE",
    "NAME_PLATE_UNIT_ADDED", "NAME_PLATE_UNIT_REMOVED", "CHAT_MSG_ADDON", "CURSOR_CHANGED", "MODIFIER_STATE_CHANGED",
    "UPDATE_MOUSEOVER_UNIT", "PLAYER_TARGET_CHANGED", "UNIT_TARGET", "CHAT_MSG_CHANNEL", "WORLD_CURSOR_TOOLTIP_UPDATE",
})


def iter_calls(root: Node) -> Iterator[tuple[Node, str]]:
    """Yield ``(call_node, name)`` for Call and Method nodes. Methods are named ``:Name``."""
    for node in root.walk():
        if node.kind in ("Call", "Method"):
            name = call_name(node)
            if name:
                yield node, name


def call_args(node: Node) -> list[Node]:
    return list(node.args)


def is_global_ref(node: Node, name: str | None = None) -> bool:
    """Name (or dotted chain rooted at a global Name) that resolves to a global."""
    r = root_name(node)
    if r is None or not r.a.get("is_global"):
        return False
    return name is None or dotted_name(node) == name


def text_of(node: Node) -> str:
    """Rough textual rendering (names/strings only) for guard matching."""
    parts: list[str] = []
    for n in node.walk():
        if n.kind == "Name":
            parts.append(n.id)
        elif n.kind == "String":
            parts.append(str(n.value))
        elif n.kind == "Method":
            parts.append(n.name)
    return " ".join(parts)


def mentions(node: Node, name: str) -> bool:
    """Does ``node`` reference ``name`` (Name id or dotted name of an Index chain)?"""
    for n in node.walk():
        if n.kind == "Name" and n.id == name:
            return True
        if n.kind in ("Index",) and dotted_name(n) == name:
            return True
        if n.kind == "Call" and name.startswith(":") is False and dotted_name(n.func) == name:
            return True
    return False


def guarded_by(node: Node, name: str) -> bool:
    """True if ``node`` executes only when ``name`` is truthy/checked.

    Recognises ``if name then``, ``if not name then return end`` before it, ``name and name()``,
    ``if C_X and C_X.Y then`` and ``type(name) == "function"``.
    """
    prev = node
    for anc in node.ancestors():
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if body is prev or _contains(body, node):
                    if mentions(cond, name):
                        return True
        elif anc.kind == "BinOp" and anc.op == "and" and _contains(anc.right, node):
            if mentions(anc.left, name):
                return True
        elif anc.kind == "Block":
            # early return: `if not X then return end` earlier in the same block
            for st in anc.body:
                if _contains(st, node):
                    break
                if st.kind == "If" and mentions(st.clauses[0][0], name) and _returns(st.clauses[0][1]):
                    return True
        if anc.kind == "Function":
            # keep looking in outer scopes too (file-level guards wrap whole modules)
            pass
        prev = anc
    return False


def existence_checked(node: Node, name: str) -> bool:
    """The code tests whether ``name`` exists before relying on it.

    Covers :func:`guarded_by`, ``X or fallback``, ``if X then`` / ``not X`` (the read *is* the check) and
    ``type(X) == "function"``.
    """
    if guarded_by(node, name):
        return True
    p = node.parent
    # walk up through Index chains: `X.Y or Z`
    cur = node
    while p is not None and p.kind == "Index" and p.obj is cur:
        cur, p = p, p.parent
    if p is None:
        return False
    if p.kind == "BinOp" and p.op in ("or", "and") and p.left is cur:
        return True
    if p.kind == "BinOp" and p.op == "or" and p.right is cur:
        return True  # `C_X and C_X.F or LegacyF` fallback chain
    if p.kind == "UnOp" and p.op == "not":
        return True
    if p.kind == "If" and any(c is cur for c, _ in p.clauses):
        return True
    if p.kind == "BinOp" and p.op in ("==", "~=") and (p.left.kind == "Nil" or p.right.kind == "Nil"):
        return True
    if p.kind == "Call" and dotted_name(p.func) == "type":
        return True
    return False


def find_names_at(lf: LuaFile, line: int, name: str) -> list[Node]:
    if lf.ast is None:
        return []
    return [n for n in lf.ast.walk() if n.kind == "Name" and n.line == line and n.id == name]


def _returns(block: Node) -> bool:
    return any(st.kind in ("Return", "Break") for st in block.body)


def _contains(outer: Node, inner: Node) -> bool:
    if outer is inner:
        return True
    return any(a is outer for a in inner.ancestors())


def guarded_by_call(node: Node, func_name: str) -> bool:
    """Like :func:`guarded_by` but for a call such as ``InCombatLockdown()`` anywhere in a guarding
    condition, or an earlier ``if InCombatLockdown() then ... return end`` in the enclosing function."""
    return guarded_by(node, func_name)


@dataclass
class ScriptHandler:
    script: str  # OnUpdate, OnEvent, ...
    owner: Node  # the SetScript/HookScript method call
    func: Node | None  # resolved Function node (None if unresolvable)
    file: LuaFile


def resolve_function(ctx: AuditContext, lf: LuaFile, expr: Node) -> Node | None:
    """Resolve an expression used as a callback to its ``Function`` node."""
    if expr.kind == "Function":
        return expr
    if expr.kind == "Name":
        decl = expr.a.get("decl")
        if decl is not None:
            parent = decl.parent
            if parent is not None and parent.kind == "LocalFunction":
                return parent.func
            if parent is not None and parent.kind == "Local":
                idx = next((i for i, n in enumerate(parent.names) if n is decl), -1)
                if 0 <= idx < len(parent.values) and parent.values[idx].kind == "Function":
                    return parent.values[idx]
            # later assignment `name = function ... end`
            for ref in decl.a.get("refs", []):
                p = ref.parent
                if p is not None and p.kind == "Assign" and ref in p.targets:
                    i = p.targets.index(ref)
                    if i < len(p.values) and p.values[i].kind == "Function":
                        return p.values[i]
        return _function_by_name(ctx, expr.id)
    name = dotted_name(expr)
    if name:
        return _function_by_name(ctx, name)
    return None


def _function_by_name(ctx: AuditContext, name: str) -> Node | None:
    table = function_table(ctx)
    return table.get(name)


def function_table(ctx: AuditContext) -> dict[str, Node]:
    """Dotted name -> Function for ``function a.b:c()`` decls and ``a.b = function`` assigns (addon-wide).

    Methods are stored both as ``a.b.c`` and ``a.b:c``.
    """
    cache = getattr(ctx, "_fn_table", None)
    if cache is not None:
        return cache
    table: dict[str, Node] = {}
    for f in ctx.parsed_files():
        assert f.ast is not None
        for node in f.ast.walk():
            if node.kind == "FunctionDecl":
                n = dotted_name(node.target)
                if n:
                    table.setdefault(n, node.func)
                    if node.is_method:
                        base, _, last = n.rpartition(".")
                        table.setdefault(f"{base}:{last}", node.func)
            elif node.kind == "LocalFunction":
                table.setdefault(node.name.id, node.func)
            elif node.kind == "Assign":
                for i, tg in enumerate(node.targets):
                    if i < len(node.values) and node.values[i].kind == "Function":
                        n = dotted_name(tg)
                        if n:
                            table.setdefault(n, node.values[i])
    ctx._fn_table = table  # type: ignore[attr-defined]
    return table


def script_handlers(ctx: AuditContext, lf: LuaFile, scripts: set[str] | None = None) -> list[ScriptHandler]:
    out = []
    assert lf.ast is not None
    for node in lf.ast.walk():
        if node.kind == "Method" and node.name in ("SetScript", "HookScript") and node.args:
            script = string_arg(node, 0)
            if script is None or (scripts and script not in scripts):
                continue
            func = resolve_function(ctx, lf, node.args[1]) if len(node.args) > 1 else None
            out.append(ScriptHandler(script, node, func, lf))
    return out


def registered_events(ctx: AuditContext) -> dict[str, list[tuple[LuaFile, Node]]]:
    """Event name -> RegisterEvent/RegisterUnitEvent call sites (addon-wide)."""
    cache = getattr(ctx, "_events", None)
    if cache is not None:
        return cache
    out: dict[str, list[tuple[LuaFile, Node]]] = {}
    for f in ctx.parsed_files():
        assert f.ast is not None
        for node, name in iter_calls(f.ast):
            if name in (":RegisterEvent", ":RegisterUnitEvent", "RegisterEvent") or name.endswith(".RegisterEvent"):
                ev = string_arg(node, 0) if node.kind == "Method" else string_arg(node, 1) or string_arg(node, 0)
                if ev and EVENT_NAME.match(ev):
                    out.setdefault(ev, []).append((f, node))
    ctx._events = out  # type: ignore[attr-defined]
    return out


def event_handler_functions(ctx: AuditContext) -> dict[int, tuple[Node, set[str]]]:
    """id(Function) -> (Function, events it handles). Covers OnEvent handlers and ``obj:EVENT_NAME()``
    methods for registered events."""
    cache = getattr(ctx, "_event_fns", None)
    if cache is not None:
        return cache
    events = set(registered_events(ctx))
    out: dict[int, tuple[Node, set[str]]] = {}
    for f in ctx.parsed_files():
        for h in script_handlers(ctx, f, {"OnEvent"}):
            if h.func is not None:
                out[id(h.func)] = (h.func, set(events))
    for name, fn in function_table(ctx).items():
        last = re.split(r"[.:]", name)[-1]
        if EVENT_NAME.match(last) and last in events:
            entry = out.setdefault(id(fn), (fn, set()))
            entry[1].add(last)
    ctx._event_fns = out  # type: ignore[attr-defined]
    return out


def hot_functions(ctx: AuditContext) -> dict[int, tuple[Node, str]]:
    """id(Function) -> (Function, reason). OnUpdate handlers, frequent-event handlers, and local
    functions they call directly (one level)."""
    cache = getattr(ctx, "_hot", None)
    if cache is not None:
        return cache
    hot: dict[int, tuple[Node, str]] = {}
    for f in ctx.parsed_files():
        for h in script_handlers(ctx, f, {"OnUpdate"}):
            if h.func is not None:
                hot[id(h.func)] = (h.func, "OnUpdate handler (runs every frame)")
    for fn, evs in event_handler_functions(ctx).values():
        freq = evs & FREQUENT_EVENTS
        if freq:
            hot.setdefault(id(fn), (fn, f"handler for frequent event {sorted(freq)[0]}"))
    # one level of direct calls
    for fn, reason in list(hot.values()):
        for node, _name in iter_calls(fn.body):
            target = node.func if node.kind == "Call" else None
            if target is None:
                continue
            for f in ctx.parsed_files():
                if f.ast is not None and _contains(f.ast, node):
                    callee = resolve_function(ctx, f, target)
                    if callee is not None and id(callee) not in hot:
                        hot[id(callee)] = (callee, f"called from {reason}")
                    break
    ctx._hot = hot  # type: ignore[attr-defined]
    return hot


def enclosing_functions(node: Node) -> list[Node]:
    return [a for a in node.ancestors() if a.kind == "Function"]


def innermost_hot(ctx: AuditContext, node: Node) -> tuple[Node, str] | None:
    """If ``node`` sits (directly, not inside a nested closure) in a hot function, return it."""
    hot = hot_functions(ctx)
    for anc in node.ancestors():
        if anc.kind == "Function":
            return hot.get(id(anc))
    return None


def in_loop(node: Node, stop: Node | None = None) -> Node | None:
    for anc in node.ancestors():
        if anc is stop or anc.kind == "Function":
            return None
        if anc.kind in ("While", "Repeat", "NumFor", "GenFor"):
            return anc
    return None


def file_scope(node: Node) -> bool:
    """Executes at load time (not inside any function)."""
    return not any(a.kind == "Function" for a in node.ancestors())


def method_target_name(node: Node) -> str | None:
    """For ``obj:Method()`` return the dotted name of ``obj`` (``MyFrame``, ``addon.frame``)."""
    if node.kind == "Method":
        return dotted_name(node.obj)
    return None
