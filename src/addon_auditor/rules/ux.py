"""UX rule pack: how the addon feels to the player (slash commands, windows, login noise, options, tooltips).

These rules are heuristic by nature. They stay quiet whenever a frame escapes to code they cannot see
(returned, handed to an unresolvable helper) and prefer ``info``/``warn`` with medium or low confidence.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from ..core.context import AuditContext, LuaFile
from ..core.finding import Emit, rule
from ..core.lua_ast import Node, call_name, dotted_name, string_arg
from ._util import EVENT_NAME, event_handler_functions, function_table, iter_calls, resolve_function, text_of

LOGIN_EVENTS = frozenset({"ADDON_LOADED", "PLAYER_LOGIN", "PLAYER_ENTERING_WORLD", "VARIABLES_LOADED"})
_WINDOW_TEMPLATE = re.compile(
    r"^(?:BasicFrameTemplate\w*|ButtonFrameTemplate\w*|PortraitFrameTemplate\w*|PortraitFrameFlatTemplate\w*"
    r"|UIPanelDialogTemplate|DefaultPanelTemplate|DefaultPanelFlatTemplate)$")
_DISPATCH_VARS = frozenset({"event", "evt", "addon", "addonname", "addon_name", "name", "arg1", "loaded",
                            "loadedaddon", "loadedname", "addonloaded"})
_OPTIONS_CALLS = re.compile(
    r"\bSettings\s*\.\s*Register(?:CanvasLayout|VerticalLayout)Category\b|\bSettings\s*\.\s*RegisterAddOnCategory\b"
    r"|\bInterfaceOptions_AddCategory\b|AceConfigDialog|AceConfig-3\.0|\bLibStub\s*\(\s*[\"']AceConfig")
_SETTINGS_PATH = re.compile(r"\bSettings\s*\.\s*Register(?:CanvasLayout|VerticalLayout)Category\b")
_SETTINGS_DB = re.compile(
    r"\.(?:settings|options|config|profile)\b|\b(?:defaults|DEFAULTS|DEFAULT_SETTINGS|DEFAULT_OPTIONS|"
    r"DEFAULT_CONFIG|defaultSettings|defaultOptions)\s*=")
_MINIMAP_HIDE = re.compile(
    r"\.hide\b|\[\s*[\"']hide[\"']\s*\]|[{,]\s*hide\s*=|\bhide\s*=\s*(?:true|false)"
    r"|[Ss]how_?[Mm]inimap|[Hh]ide_?[Mm]inimap|[Mm]inimap_?(?:[Hh]ide|[Hh]idden|[Ss]how|[Ss]hown)\b"
    r"|[Mm]inimap_?(?:[Ii]con|[Bb]utton)_?(?:[Ss]hown|[Hh]idden|[Ee]nabled)\b")
_HELP_WORD = re.compile(r"\b(?:help|usage|commands?)\b", re.I)
_COLOR = re.compile(r"\|c[0-9a-fA-F]{8}|\|r|\|T[^|]*\|t|\|n")
_SENTENCE = re.compile(r"^[A-Za-z][A-Za-z']*(?:[ ,.:!?\-]+[A-Za-z][A-Za-z']*){2,}[.!?:]?$")
_NONCHAT_FRAMES = ("DEFAULT_CHAT_FRAME", "ChatFrame1", "SELECTED_CHAT_FRAME")
_SAFE_CALLEES = frozenset({
    "tinsert", "table.insert", "Mixin", "type", "print", "tostring", "ipairs", "pairs", "setmetatable",
    "rawget", "rawset", "assert", "select", "unpack", "wipe", "table.remove", "tremove", "hooksecurefunc",
    "PixelUtil.SetPoint", "PixelUtil.SetSize", "PixelUtil.SetWidth", "PixelUtil.SetHeight", "CreateFrame",
    "GameTooltip_SetDefaultAnchor", "C_Timer.After",
})


# --------------------------------------------------------------------------- small helpers


def _contains(outer: Node, inner: Node) -> bool:
    return outer is inner or any(a is outer for a in inner.ancestors())


def _enclosing_fn(node: Node) -> Node | None:
    return next((a for a in node.ancestors() if a.kind == "Function"), None)


def _is_true(node: Node | None) -> bool:
    return node is not None and node.kind not in ("False", "Nil")


def _strings(node: Node) -> Iterator[str]:
    for n in node.walk():
        if n.kind == "String":
            yield str(n.value)


def _all_text(ctx: AuditContext) -> str:
    cache = getattr(ctx, "_ux_text", None)
    if cache is None:
        cache = "\n".join(lf.src for lf in ctx.lua_files()) + "\n" + "\n".join(x.text for x in ctx.xml_files.values())
        ctx._ux_text = cache  # type: ignore[attr-defined]
    return cache


def _key(expr: Node | None) -> tuple[str, object] | None:
    """Identity of a frame-holding expression: local decl, global name, or dotted text (file-wide)."""
    if expr is None:
        return None
    if expr.kind == "Paren":
        return _key(expr.expr)
    if expr.kind == "Name":
        if expr.a.get("is_decl"):
            return ("L", id(expr))
        decl = expr.a.get("decl")
        if decl is not None:
            return ("L", id(decl))
        return ("G", expr.id)
    if expr.kind == "Index":
        d = dotted_name(expr)
        if d:
            return ("D", d)
    return None


def _is_print(node: Node) -> bool:
    """print(...), DEFAULT_CHAT_FRAME:AddMessage(...), addon Print wrappers (ns.Print, self:Print)."""
    name = call_name(node)
    if not name:
        return False
    if node.kind == "Call":
        last = name.rsplit(".", 1)[-1]
        return last in ("print", "Print") or name in ("ChatFrame_AddMessage",)
    if name == ":Print":
        return True
    if name == ":AddMessage":
        obj = dotted_name(node.obj) or ""
        return obj in _NONCHAT_FRAMES or bool(re.match(r"^ChatFrame\d+$", obj))
    return False


def _callee(ctx: AuditContext, lf: LuaFile, call: Node) -> Node | None:
    if call.kind == "Call":
        return resolve_function(ctx, lf, call.func)
    if call.kind == "Method":
        base = dotted_name(call.obj)
        if base:
            return function_table(ctx).get(f"{base}:{call.name}")
    return None


# --------------------------------------------------------------------------- frame records


@dataclass
class _Frame:
    lf: LuaFile
    call: Node
    key: tuple[str, object] | None
    var: str  # how the code refers to it
    name: str | None  # literal global name
    name_expr: Node | None
    template_expr: Node | None
    parent: str | None
    methods: list[Node] = field(default_factory=list)
    why: list[str] = field(default_factory=list)  # reasons it escapes to code we cannot see
    returned_by: list[Node] = field(default_factory=list)  # builder functions that return it

    @property
    def opaque(self) -> bool:
        return bool(self.why)

    @property
    def templates(self) -> list[str] | None:
        """Literal templates; [] when none given, None when not a literal."""
        t = self.template_expr
        if t is None or t.kind == "Nil":
            return []
        if t.kind == "String":
            return [s.strip() for s in str(t.value).split(",") if s.strip()]
        return None

    def has(self, method: str, truthy: bool = False) -> list[Node]:
        out = [m for m in self.methods if m.name == method]
        if truthy:
            out = [m for m in out if not m.args or _is_true(m.args[0])]
        return out

    def scripts(self, script: str) -> list[Node]:
        """Handler expressions set with SetScript/HookScript."""
        out = []
        for m in self.methods:
            if m.name in ("SetScript", "HookScript") and string_arg(m, 0) == script and len(m.args) > 1:
                out.append(m.args[1])
        return out


def _frames(ctx: AuditContext) -> list[_Frame]:
    cache = getattr(ctx, "_ux_frames", None)
    if cache is not None:
        return cache
    frames: list[_Frame] = []
    for lf in ctx.parsed_files():
        frames.extend(_file_frames(ctx, lf))
    ctx._ux_frames = frames  # type: ignore[attr-defined]
    for rec in frames:
        for fn in rec.returned_by:
            _follow_return(ctx, rec, fn)
    return frames


def _lf_of(ctx: AuditContext, node: Node) -> LuaFile | None:
    top = node
    for a in node.ancestors():
        top = a
    return next((lf for lf in ctx.parsed_files() if lf.ast is top), None)


def _follow_return(ctx: AuditContext, rec: _Frame, fn: Node) -> None:
    """``local f = BuildWindow()`` at each call site: methods on ``f`` there configure the same frame."""
    sites = _call_sites(ctx).get(id(fn), [])
    if not sites:
        rec.why.append(f"returned by {fn.a.get('fname') or 'a function'} with no visible caller")
        return
    for site in sites:
        p = site.parent
        target: Node | None = None
        if p is not None and p.kind == "Local" and site in p.values:
            i = p.values.index(site)
            target = p.names[i] if i < len(p.names) else None
        elif p is not None and p.kind == "Assign" and site in p.values:
            i = p.values.index(site)
            target = p.targets[i] if i < len(p.targets) else None
        elif p is not None and p.kind == "Method" and p.obj is site:
            rec.methods.append(p)
            continue
        elif p is not None and p.kind == "CallStmt":
            continue
        k = _key(target)
        lf = _lf_of(ctx, site)
        if k is None or lf is None or k[0] == "D":
            rec.why.append(f"builder result escapes at line {site.line}")
            continue
        assert lf.ast is not None
        for n in lf.ast.walk():
            if n.kind == "Method" and _key(n.obj) == k:
                rec.methods.append(n)
            elif n.kind in ("Call", "Method"):
                for i, a in enumerate(n.args):
                    if _key(a) == k:
                        _absorb_arg(ctx, lf, n, i, rec)
            elif n.kind == "Return" and any(_key(v) == k for v in n.values):
                rec.why.append(f"returned again at line {n.line}")


def _file_frames(ctx: AuditContext, lf: LuaFile) -> list[_Frame]:
    assert lf.ast is not None
    recs: list[_Frame] = []
    by_key: dict[tuple[str, object], _Frame] = {}
    for node, name in iter_calls(lf.ast):
        if name != "CreateFrame" or node.kind != "Call":
            continue
        args = node.args
        target: Node | None = None
        p = node.parent
        if p is not None and p.kind == "Local" and node in p.values:
            i = p.values.index(node)
            target = p.names[i] if i < len(p.names) else None
        elif p is not None and p.kind == "Assign" and node in p.values:
            i = p.values.index(node)
            target = p.targets[i] if i < len(p.targets) else None
        name_expr = args[1] if len(args) > 1 and args[1].kind != "Nil" else None
        rec = _Frame(lf=lf, call=node, key=_key(target),
                     var=(dotted_name(target) or "") if target is not None else "",
                     name=string_arg(node, 1), name_expr=name_expr,
                     template_expr=args[3] if len(args) > 3 else None,
                     parent=dotted_name(args[2]) if len(args) > 2 else None)
        if target is None:
            rec.why.append("not stored in a variable")
        recs.append(rec)
        if rec.key is not None:
            by_key[rec.key] = rec
        if rec.name:
            by_key.setdefault(("G", rec.name), rec)
    if not by_key:
        return recs
    for node in lf.ast.walk():
        if node.kind == "Method":
            k = _key(node.obj)
            rec = by_key.get(k) if k else None
            if rec is not None:
                rec.methods.append(node)
        elif node.kind in ("Call", "Return", "Assign", "Table"):
            _track_escape(ctx, lf, node, by_key)
        if node.kind in ("Call", "Method"):
            for i, a in enumerate(node.args):
                k = _key(a)
                if k in by_key:
                    _absorb_arg(ctx, lf, node, i, by_key[k])
    return recs


def _track_escape(ctx: AuditContext, lf: LuaFile, node: Node, by_key: dict[tuple[str, object], _Frame]) -> None:
    if node.kind == "Return":
        fn = _enclosing_fn(node)
        for v in node.values:
            k = _key(v)
            if k in by_key:
                if fn is None or len(node.values) > 1:
                    by_key[k].why.append(f"returned at line {node.line}")
                elif fn not in by_key[k].returned_by:
                    by_key[k].returned_by.append(fn)
    elif node.kind == "Table":
        for f in node.fields:
            k = _key(f.value)
            if k in by_key:
                by_key[k].why.append(f"stored in a table at line {node.line}")
    elif node.kind == "Assign":
        for i, v in enumerate(node.values):
            k = _key(v)
            if k in by_key and i < len(node.targets):
                rec = by_key[k]
                tk = _key(node.targets[i])
                if tk is not None and tk[0] == "D":
                    rec.why.append(f"exported as {tk[1]} at line {node.line}")
                elif tk is not None:
                    by_key.setdefault(tk, rec)


def _absorb_arg(ctx: AuditContext, lf: LuaFile, node: Node, i: int, rec: _Frame) -> None:
    """Frame passed to a helper: inline the helper's method calls on that parameter (one level)."""
    name = call_name(node) or ""
    if name in _SAFE_CALLEES or name.startswith(":Set") or name in (":ClearAllPoints",):
        return  # anchoring a sibling to it, etc.
    if name == "pcall" and node.args and i > 0:
        fn = resolve_function(ctx, lf, node.args[0])
        i -= 1
    else:
        fn = _callee(ctx, lf, node)
    if fn is None:
        rec.why.append(f"passed to unresolved {name} at line {node.line}")
        return
    idx = i + (1 if node.kind == "Method" and fn.params and fn.params[0].a.get("implicit") else 0)
    if idx >= len(fn.params):
        rec.why.append(f"passed as vararg to {name} at line {node.line}")
        return
    param = fn.params[idx]
    for n in fn.body.walk():
        if n.kind == "Method" and n.obj.kind == "Name" and n.obj.a.get("decl") is param:
            if n not in rec.methods:
                rec.methods.append(n)
        elif n.kind == "Return" and any(v.kind == "Name" and v.a.get("decl") is param for v in n.values):
            rec.why.append(f"returned by helper {name}")


def _is_top_level(rec: _Frame) -> bool:
    return rec.parent in (None, "UIParent")


def _window_signal(rec: _Frame, frames: list[_Frame]) -> str | None:
    if not _is_top_level(rec) or rec.call.args and string_arg(rec.call, 0) not in ("Frame", None):
        return None
    tpls = rec.templates or []
    for t in tpls:
        if _WINDOW_TEMPLATE.match(t):
            return f"uses `{t}`"
    if rec.var:
        for other in frames:
            if other.lf is rec.lf and other.parent == rec.var and any(
                    t.startswith("UIPanelCloseButton") for t in (other.templates or [])):
                return "has a close button"
    movable = bool(rec.has("SetMovable", truthy=True))
    if movable and rec.has("SetToplevel", truthy=True):
        return "is a movable top-level window"
    if movable and any(string_arg(m, 0) in ("DIALOG", "FULLSCREEN_DIALOG") for m in rec.has("SetFrameStrata")):
        return "is a movable DIALOG-strata window"
    return None


def _windows(ctx: AuditContext) -> list[tuple[_Frame, str]]:
    cache = getattr(ctx, "_ux_windows", None)
    if cache is None:
        frames = _frames(ctx)
        cache = [(r, s) for r in frames if (s := _window_signal(r, frames))]
        ctx._ux_windows = cache  # type: ignore[attr-defined]
    return cache


# --------------------------------------------------------------------------- login context


def _addon_name_vars(lf: LuaFile) -> set[str]:
    """``local addonName, ns = ...`` -> {"addonName"}."""
    out: set[str] = set()
    assert lf.ast is not None
    for st in lf.ast.body.body:
        if st.kind == "Local" and st.values and st.values[0].kind == "Vararg" and st.names:
            out.add(st.names[0].id)
    return out


def _dispatch(ctx: AuditContext, cond: Node, extra: set[str]) -> tuple[bool, set[str]]:
    """Is ``cond`` only an event / addon-name dispatch? Returns (is_dispatch, event literals)."""
    events: set[str] = set()

    def side_ok(a: Node, b: Node) -> bool:
        if a.kind == "String":
            v = str(a.value)
            if EVENT_NAME.match(v):
                events.add(v)
                return True
            return v == ctx.addon.name
        if a.kind == "Name" and (a.id.lower() in _DISPATCH_VARS or a.id in extra or a.id.endswith("ADDON_NAME")):
            return b.kind in ("Name", "String", "Index")
        return False

    def ok(e: Node) -> bool:
        if e.kind == "Paren":
            return ok(e.expr)
        if e.kind == "BinOp" and e.op in ("and", "or"):
            return ok(e.left) and ok(e.right)
        if e.kind == "BinOp" and e.op in ("==", "~="):
            a, b = side_ok(e.left, e.right), side_ok(e.right, e.left)
            return a or b
        return False

    return ok(cond), events


_SETTING_WORDS = re.compile(
    r"(?i)db|settings?|options?|config|profile|verbose|quiet|silent|debug|seen|first|welcome|intro|announce|"
    r"show|enable|disable|message|notify|version|chat|print|login|greet|spam|mute")


def _gating(ctx: AuditContext, node: Node, extra: set[str]) -> tuple[Node | None, bool, set[str]]:
    """(enclosing function, gated, event literals the path requires).

    Setting / first-run / debug conditions gate both branches. Other conditions (``if n == 0``) gate their
    ``then`` branch only: the ``else`` and code after a nil-guard ``return`` are the normal path.
    """
    prev = node
    events: set[str] = set()
    for anc in node.ancestors():
        if anc.kind == "Function":
            return anc, False, events
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if _contains(cond, node):
                    return None, True, events
                if body is prev:
                    disp, ev = _dispatch(ctx, cond, extra)
                    if not disp:
                        return None, True, events
                    events |= ev
                    break
            else:
                if anc.a.get("orelse") is prev:
                    conds = [c for c, _b in anc.clauses]
                    if any(_dispatch(ctx, c, extra)[0] for c in conds):
                        return None, True, events  # else of an event branch: some other event
                    if any(_SETTING_WORDS.search(text_of(c)) for c in conds):
                        return None, True, events
        elif anc.kind == "BinOp" and anc.op in ("and", "or") and _contains(anc.right, node):
            disp, ev = _dispatch(ctx, anc.left, extra)
            if not disp:
                return None, True, events
            events |= ev
        elif anc.kind == "Block":
            for st in anc.body:
                if _contains(st, node):
                    break
                if st.kind == "If" and any(s.kind in ("Return", "Break") for s in st.clauses[0][1].body):
                    cond = st.clauses[0][0]
                    disp, ev = _dispatch(ctx, cond, extra)
                    if disp:
                        events |= {e for e in ev if _negated_event(cond, e)}
                    elif _SETTING_WORDS.search(text_of(cond)):
                        return None, True, events
        prev = anc
    return None, False, events


def _negated_event(cond: Node, event: str) -> bool:
    """``if event ~= "X" then return end`` means the rest runs for X."""
    for n in cond.walk():
        if n.kind == "BinOp" and n.op == "~=" and any(
                s.kind == "String" and s.value == event for s in (n.left, n.right)):
            return True
    return False


def _reverse_fn_names(ctx: AuditContext) -> dict[int, list[str]]:
    cache = getattr(ctx, "_ux_rev", None)
    if cache is None:
        cache = {}
        for n, fn in function_table(ctx).items():
            cache.setdefault(id(fn), []).append(n)
        ctx._ux_rev = cache  # type: ignore[attr-defined]
    return cache


def _call_sites(ctx: AuditContext) -> dict[int, list[Node]]:
    cache = getattr(ctx, "_ux_sites", None)
    if cache is None:
        cache = {}
        for lf in ctx.parsed_files():
            assert lf.ast is not None
            for node, _n in iter_calls(lf.ast):
                fn = _callee(ctx, lf, node)
                if fn is not None:
                    cache.setdefault(id(fn), []).append(node)
        ctx._ux_sites = cache  # type: ignore[attr-defined]
    return cache


def _on_login(ctx: AuditContext, node: Node, extra: set[str], depth: int = 0) -> bool:
    """``node`` runs unconditionally while the addon loads / the player logs in."""
    fn, gated, events = _gating(ctx, node, extra)
    if gated:
        return False
    if fn is None:
        return True  # file scope
    if events:
        return bool(events & LOGIN_EVENTS)
    names = _reverse_fn_names(ctx).get(id(fn), []) + ([fn.fname] if fn.a.get("fname") else [])
    lasts = {re.split(r"[.:]", n)[-1] for n in names}
    if lasts & LOGIN_EVENTS or lasts & {"OnInitialize", "OnEnable"}:
        return True
    if any(re.search(r"debug", n, re.I) for n in names):
        return False
    if id(fn) in event_handler_functions(ctx):
        return False  # OnEvent without an event branch: cannot tell which event
    if depth >= 2:
        return False
    p = fn.parent
    if p is not None and p.kind == "Call" and dotted_name(p.func) == "C_Timer.After":
        return _on_login(ctx, p, extra, depth + 1)
    return any(_on_login(ctx, site, extra, depth + 1) for site in _call_sites(ctx).get(id(fn), []))


# --------------------------------------------------------------------------- slash commands


def _slash_handlers(ctx: AuditContext) -> list[tuple[LuaFile, Node, Node | None, str]]:
    out = []
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for node in lf.ast.walk():
            if node.kind != "Assign":
                continue
            for i, tg in enumerate(node.targets):
                if tg.kind != "Index" or dotted_name(tg.obj) != "SlashCmdList" or i >= len(node.values):
                    continue
                key = str(tg.key.value) if tg.key.kind == "String" else "?"
                out.append((lf, node, resolve_function(ctx, lf, node.values[i]), key))
    return out


def _has_slash(ctx: AuditContext) -> bool:
    if any(n.startswith("SLASH_") for n in ctx.addon_globals):
        return True
    return bool(re.search(r":RegisterChatCommand\s*\(|AceConsole", _all_text(ctx)))


@rule("UX001", "ux", "info", "Windowed addon without a slash command",
      "The addon builds a window but registers no `/command`, so players cannot open it from chat or a macro.",
      scope="addon", confidence="medium")
def no_slash_command(ctx: AuditContext, emit: Emit) -> None:
    wins = _windows(ctx)
    if not wins or _has_slash(ctx):
        return
    rec, _sig = wins[0]
    emit(rec.call.line, f"`{rec.name or rec.var or 'frame'}` is a window but the addon registers no slash command.",
         file=rec.lf.rel,
         fix_hint=f"Add `SLASH_{ctx.addon.name.upper()}1 = \"/{ctx.addon.name.lower()[:8]}\"` and "
                  f"`SlashCmdList.{ctx.addon.name.upper()} = function(msg) ... end` that toggles the window "
                  "(and `help` / `options` sub-commands).")


def _features(ctx: AuditContext) -> int:
    text = _all_text(ctx)
    return sum((bool(_windows(ctx)), bool(_minimap_buttons(ctx)), bool(_OPTIONS_CALLS.search(text))))


def _handler_bodies(ctx: AuditContext, lf: LuaFile, fn: Node, depth: int = 0) -> list[Node] | None:
    """fn plus helpers it hands ``msg`` to; None when msg goes somewhere unresolvable."""
    out = [fn]
    if not fn.params or depth > 1:
        return out
    msg = fn.params[0]
    for ref in msg.a.get("refs", []):
        p = ref.parent
        if p is not None and p.kind in ("Call", "Method") and ref in p.args:
            name = call_name(p) or ""
            if name in ("print", "tostring", "type", "strtrim", "strlower", "string.lower", "string.trim"):
                continue
            callee = _callee(ctx, lf, p)
            if callee is None:
                return None
            sub = _handler_bodies(ctx, lf, callee, depth + 1)
            if sub is None:
                return None
            out.extend(sub)
    return out


def _has_help(bodies: list[Node]) -> bool:
    for body in bodies:
        for s in _strings(body):
            low = s.strip().lower()
            if low in ("help", "?", "h", "-h", "--help") or _HELP_WORD.search(s):
                return True
        tail = body.body.body[-2:]
        for n, name in iter_calls(body):
            if re.search(r"help|usage", name, re.I):
                return True
            if not _is_print(n):
                continue
            # a print in the fallback (an else branch, or after the `if cmd == ... return end` chain)
            if any(st is n.parent for st in tail):
                return True
            for anc in n.ancestors():
                if anc is body:
                    break
                if anc.kind == "If" and anc.a.get("orelse") is not None and _contains(anc.orelse, n):
                    return True
    return False


@rule("UX002", "ux", "info", "Slash command ignores its arguments or has no help",
      "A slash handler that ignores `msg`, or answers unknown input silently, leaves players guessing what "
      "the addon can do.", scope="addon", confidence="medium")
def slash_no_help(ctx: AuditContext, emit: Emit) -> None:
    for lf, assign, fn, key in _slash_handlers(ctx):
        if fn is None:
            continue
        msg = fn.params[0] if fn.params else None
        if msg is None or not msg.a.get("refs"):
            if _features(ctx) >= 2:
                emit(assign.line, f"`SlashCmdList.{key}` ignores its argument although the addon has several "
                                  "features (window, options, minimap button).",
                     file=lf.rel,
                     fix_hint="Parse `msg` (`local cmd = (msg or \"\"):lower():match(\"^%s*(%S*)\")`) and add "
                              "sub-commands such as `options`, `minimap` and `help`.")
            continue
        bodies = _handler_bodies(ctx, lf, fn)
        if bodies is None or _has_help(bodies):
            continue
        emit(assign.line, f"`SlashCmdList.{key}` has no `help` branch and no usage message for unknown input.",
             file=lf.rel,
             fix_hint="Handle `cmd == \"help\"` (and the final `else`) by printing each sub-command, e.g. "
                      "`print(\"/myaddon options - open settings\")`.")


# --------------------------------------------------------------------------- windows


def _esc_names(ctx: AuditContext) -> tuple[set[str], set[str]]:
    """(literal names in UISpecialFrames/UIPanelWindows, non-literal expression texts)."""
    names: set[str] = set()
    exprs: set[str] = set()
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for node in lf.ast.walk():
            if node.kind == "Call" and call_name(node) in ("tinsert", "table.insert") and len(node.args) >= 2:
                if dotted_name(node.args[0]) in ("UISpecialFrames", "_G.UISpecialFrames"):
                    a = node.args[-1]
                    if a.kind == "String":
                        names.add(str(a.value))
                    else:
                        exprs.add(text_of(a))
            elif node.kind == "Index" and dotted_name(node.obj) in ("UISpecialFrames", "UIPanelWindows"):
                p = node.parent
                if node.obj is not None and dotted_name(node.obj) == "UIPanelWindows":
                    if node.key.kind == "String":
                        names.add(str(node.key.value))
                    else:
                        exprs.add(text_of(node.key))
                elif p is not None and p.kind == "Assign" and node in p.targets:
                    i = p.targets.index(node)
                    v = p.values[i] if i < len(p.values) else None
                    if v is not None and v.kind == "String":
                        names.add(str(v.value))
                    elif v is not None:
                        exprs.add(text_of(v))
    for xf in ctx.xml_files.values():
        names |= set(re.findall(r"UISpecialFrames\s*,\s*[\"']([A-Za-z_]\w*)[\"']", xf.text))
    return names, exprs


@rule("UX003", "ux", "warn", "Window does not close with Escape",
      "Players expect Esc to close addon windows. Add the frame's global name to `UISpecialFrames` "
      "(or register it in `UIPanelWindows`).", scope="addon", confidence="medium")
def window_no_escape(ctx: AuditContext, emit: Emit) -> None:
    names, exprs = _esc_names(ctx)
    for rec, sig in _windows(ctx):
        if rec.name and rec.name in names:
            continue
        if rec.name_expr is not None and rec.name is None and text_of(rec.name_expr) in exprs:
            continue
        if rec.var and any(rec.var in e for e in exprs):
            continue
        if any(m.name in ("SetScript", "HookScript") and string_arg(m, 0) == "OnKeyDown" for m in rec.methods):
            continue
        label = rec.name or rec.var or "window"
        if rec.name is None and rec.name_expr is None:
            hint = (f"Give the frame a global name (`CreateFrame(\"Frame\", \"{ctx.addon.name}Frame\", UIParent, ...)`) "
                    f"and `tinsert(UISpecialFrames, \"{ctx.addon.name}Frame\")`.")
        else:
            hint = f"`tinsert(UISpecialFrames, \"{rec.name or label}\")` right after creating it."
        emit(rec.call.line, f"Window `{label}` ({sig}) is not in `UISpecialFrames`, so Esc does not close it.",
             file=rec.lf.rel, fix_hint=hint)
    # XML windows
    for xf in ctx.xml_files.values():
        for m in re.finditer(r"<Frame\b([^>]*)>", xf.text):
            attrs = m.group(1)
            name = re.search(r"\bname\s*=\s*\"([A-Za-z_]\w*)\"", attrs)
            inh = re.search(r"\binherits\s*=\s*\"([^\"]+)\"", attrs)
            if not name or not inh or re.search(r"\bvirtual\s*=\s*\"true\"", attrs):
                continue
            tpl = next((t.strip() for t in inh.group(1).split(",") if _WINDOW_TEMPLATE.match(t.strip())), None)
            if tpl is None or name.group(1) in names:
                continue
            line = xf.text.count("\n", 0, m.start()) + 1
            emit(line, f"Window `{name.group(1)}` (uses `{tpl}`) is not in `UISpecialFrames`, so Esc does not close it.",
                 file=xf.rel, fix_hint=f"`tinsert(UISpecialFrames, \"{name.group(1)}\")` in its OnLoad or your init code.")


def _movable(ctx: AuditContext) -> list[_Frame]:
    return [r for r in _frames(ctx) if r.has("SetMovable", truthy=True) and r.parent != "Minimap"]


@rule("UX004", "ux", "warn", "Movable frame not clamped to screen",
      "A movable frame without `SetClampedToScreen(true)` can be dragged (or restored after a resolution "
      "change) off-screen, where the player cannot reach it again.", scope="addon", confidence="medium")
def movable_not_clamped(ctx: AuditContext, emit: Emit) -> None:
    for rec in _movable(ctx):
        if rec.opaque or rec.has("SetClampedToScreen", truthy=True):
            continue
        label = rec.name or rec.var or "frame"
        emit(rec.has("SetMovable", truthy=True)[0].line,
             f"`{label}` is movable but not clamped to the screen.", file=rec.lf.rel,
             fix_hint=f"`{rec.var or 'frame'}:SetClampedToScreen(true)` next to `SetMovable(true)`.")


def _handler_text(ctx: AuditContext, lf: LuaFile, expr: Node, depth: int = 0) -> str | None:
    """Text of a script handler plus helpers it calls directly; None if unresolvable."""
    if expr.kind == "Index":
        return text_of(expr)
    fn = resolve_function(ctx, lf, expr)
    if fn is None:
        return None
    parts = [text_of(fn)]
    if depth == 0:
        for call, _n in iter_calls(fn.body):
            callee = _callee(ctx, lf, call)
            if callee is not None and callee is not fn:
                parts.append(text_of(callee))
    return " ".join(parts)


def _drag_sources(rec: _Frame, frames: list[_Frame]) -> list[_Frame]:
    """The frame itself plus drag-bar children whose handlers move it (``container:StartMoving()``)."""
    out = [rec]
    if rec.var:
        for other in frames:
            if other is not rec and other.lf is rec.lf and any(
                    rec.var in text_of(h) for h in other.scripts("OnDragStart") if h.kind == "Function"):
                out.append(other)
    return out


@rule("UX005", "ux", "info", "Movable frame position is not saved",
      "If the position is not stored (SavedVariables, `SetUserPlaced(true)` or the client layout cache for named "
      "frames), the frame jumps back to its default spot every reload.", scope="addon", confidence="low")
def movable_not_saved(ctx: AuditContext, emit: Emit) -> None:
    frames = _frames(ctx)
    for rec in _movable(ctx):
        if rec.opaque or rec.has("SetUserPlaced", truthy=True):
            continue
        layout_cached = rec.name_expr is not None and not rec.has("SetDontSavePosition", truthy=True)
        if layout_cached:
            continue
        stops: list[str | None] = []
        for src in _drag_sources(rec, frames):
            for h in src.scripts("OnDragStop") + src.scripts("OnMouseUp"):
                stops.append(_handler_text(ctx, rec.lf, h))
        if not stops or any(t is None for t in stops):
            continue
        if any(re.search(r"\bGetPoint\b|\bSetUserPlaced\b|\bGetCenter\b|\bGetLeft\b", t or "") for t in stops):
            continue
        label = rec.name or rec.var or "frame"
        emit(rec.has("SetMovable", truthy=True)[0].line,
             f"`{label}` can be dragged but its position is never saved; it resets every reload.",
             file=rec.lf.rel,
             fix_hint="In OnDragStop: `local p, _, rp, x, y = self:GetPoint()` and store it in your SavedVariables "
                      "(restore with `SetPoint` on load), or give the frame a global name so the layout cache keeps it.")


@rule("UX006", "ux", "warn", "Drag registered without a working StartMoving/StopMovingOrSizing pair",
      "`RegisterForDrag` alone does nothing; `StartMoving` without `StopMovingOrSizing` leaves the frame glued "
      "to the cursor.", scope="addon", confidence="medium")
def drag_pair(ctx: AuditContext, emit: Emit) -> None:
    for rec in _frames(ctx):
        regs = rec.has("RegisterForDrag")
        if not regs or rec.opaque:
            continue
        starts = rec.scripts("OnDragStart") + rec.scripts("OnMouseDown")
        stops = rec.scripts("OnDragStop") + rec.scripts("OnMouseUp")
        label = rec.name or rec.var or "frame"
        var = rec.var or "frame"
        if not starts:
            emit(regs[0].line, f"`{label}` registers for drag but has no OnDragStart handler, so it cannot be moved.",
                 file=rec.lf.rel,
                 fix_hint=f"`{var}:SetMovable(true)`, `{var}:SetScript(\"OnDragStart\", {var}.StartMoving)` and "
                          f"`{var}:SetScript(\"OnDragStop\", {var}.StopMovingOrSizing)`.")
            continue
        start_txt = [_handler_text(ctx, rec.lf, h) for h in starts]
        if any(t is None for t in start_txt) or not any("StartMoving" in (t or "") for t in start_txt):
            continue
        stop_txt = [_handler_text(ctx, rec.lf, h) for h in stops]
        if any(t is None for t in stop_txt):
            continue
        if not any("StopMovingOrSizing" in (t or "") for t in stop_txt):
            emit(regs[0].line, f"`{label}` starts moving on drag but never calls `StopMovingOrSizing`; "
                               "the frame stays stuck to the cursor.", file=rec.lf.rel,
                 fix_hint=f"`{var}:SetScript(\"OnDragStop\", function(self) self:StopMovingOrSizing() end)` "
                          "(save the position there too).")


# --------------------------------------------------------------------------- minimap


def _minimap_buttons(ctx: AuditContext) -> list[tuple[LuaFile, int, str]]:
    cache = getattr(ctx, "_ux_minimap", None)
    if cache is not None:
        return cache
    out: list[tuple[LuaFile, int, str]] = []
    for rec in _frames(ctx):
        if rec.parent == "Minimap":
            out.append((rec.lf, rec.call.line, rec.name or rec.var or "button"))
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for node, name in iter_calls(lf.ast):
            if name == "LibStub" and (string_arg(node, 0) or "").startswith("LibDBIcon"):
                out.append((lf, node.line, "LibDBIcon"))
    ctx._ux_minimap = out  # type: ignore[attr-defined]
    return out


@rule("UX007", "ux", "info", "Minimap button cannot be hidden",
      "The minimap ring is crowded; every minimap button needs a way to hide it (an option, `/cmd minimap`, "
      "LibDBIcon's `hide` flag).", scope="addon", confidence="medium")
def minimap_no_hide(ctx: AuditContext, emit: Emit) -> None:
    btns = _minimap_buttons(ctx)
    if not btns or _MINIMAP_HIDE.search(_all_text(ctx)):
        return
    lf, line, label = btns[0]
    emit(line, f"Minimap button `{label}` has no hide option.", file=lf.rel,
         fix_hint="Store `db.minimap = { hide = false }`, honour it when creating the button "
                  "(LibDBIcon reads `hide` itself) and add a \"Show minimap icon\" checkbox or `/cmd minimap` toggle.")


# --------------------------------------------------------------------------- options


@rule("UX008", "ux", "info", "Settings stored but no options panel",
      "The addon keeps settings in SavedVariables but registers nothing under Options -> AddOns, so players can "
      "only change them through slash commands they must discover.", scope="addon", confidence="low")
def no_options_ui(ctx: AuditContext, emit: Emit) -> None:
    svs = ctx.addon.saved_variables
    if not svs:
        return
    text = _all_text(ctx)
    if _OPTIONS_CALLS.search(text):
        return
    for lf in ctx.lua_files():
        m = _SETTINGS_DB.search(lf.src)
        if m:
            line = lf.src.count("\n", 0, m.start()) + 1
            emit(line, f"Settings live in `{svs[0]}` but there is no options panel (Settings / InterfaceOptions / "
                       "AceConfig).", file=lf.rel,
                 fix_hint="Register a panel: `local cat = Settings.RegisterVerticalLayoutCategory(\"MyAddon\")` + "
                          "`Settings.RegisterAddOnCategory(cat)`, with an `InterfaceOptions_AddCategory(panel)` "
                          "fallback for clients without `Settings`.")
            return


@rule("UX009", "ux", "warn", "Options registered only with the removed InterfaceOptions API",
      "`InterfaceOptions_AddCategory` was deprecated in 10.0 and is gone on current Mainline; without a "
      "`Settings.Register*Category` path the options page never appears there.", scope="addon",
      confidence="medium", profiles=("mainline",))
def legacy_options_only(ctx: AuditContext, emit: Emit) -> None:
    if _SETTINGS_PATH.search(_all_text(ctx)):
        return
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for node, name in iter_calls(lf.ast):
            if name == "InterfaceOptions_AddCategory":
                emit(node.line, "Options panel is registered only with `InterfaceOptions_AddCategory`; it will not "
                                "show on Mainline.", file=lf.rel,
                     fix_hint="if Settings and Settings.RegisterCanvasLayoutCategory then "
                              "local cat = Settings.RegisterCanvasLayoutCategory(panel, panel.name); "
                              "Settings.RegisterAddOnCategory(cat) else InterfaceOptions_AddCategory(panel) end")


# --------------------------------------------------------------------------- login noise


def _login_sinks(ctx: AuditContext, pred) -> list[tuple[LuaFile, Node]]:  # type: ignore[no-untyped-def]
    out = []
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        extra = _addon_name_vars(lf)
        for node, _name in iter_calls(lf.ast):
            if not pred(lf, node):
                continue
            fn = _enclosing_fn(node)
            if fn is not None and re.search(r"print|debug|log", fn.a.get("fname") or "", re.I):
                continue  # inside the Print wrapper itself / a debug helper
            if any(re.search(r"debug|warn|error|fail|missing|outdated|conflict", s, re.I) for s in _strings(node)):
                continue  # debug output and real problem reports are not login chatter
            if _on_login(ctx, node, extra):
                out.append((lf, node))
    return out


@rule("UX010", "ux", "info", "Unconditional chat output on login",
      "Every addon that prints on login pushes the player's chat up. Print once (first run) or behind an option.",
      scope="addon", confidence="medium")
def login_chat_spam(ctx: AuditContext, emit: Emit) -> None:
    sinks = _login_sinks(ctx, lambda lf, n: _is_print(n))
    if not sinks:
        return
    lf, first = sinks[0]
    where = ", ".join(f"{f.rel}:{n.line}" for f, n in sinks[:5]) + (" ..." if len(sinks) > 5 else "")
    count = len(sinks)
    msg = (f"{count} chat line{'s' if count > 1 else ''} printed unconditionally on load/login ({where}).")
    emit(first.line, msg, file=lf.rel, severity="warn" if count > 1 else None,
         fix_hint="Gate it: `if not db.loginMessageSeen then print(...) db.loginMessageSeen = true end`, or behind "
                  "a `db.settings.verbose` option (default off).")


def _window_show(ctx: AuditContext) -> dict[tuple[str, object], _Frame]:
    out: dict[tuple[str, object], _Frame] = {}
    for rec, _sig in _windows(ctx):
        if rec.key:
            out[rec.key] = rec
        if rec.name:
            out[("G", rec.name)] = rec
    return out


@rule("UX011", "ux", "warn", "Popup or window opened on every login",
      "A dialog or window that opens on every login interrupts the player before they can move. Show it once "
      "(first run / new version) and remember that in SavedVariables.", scope="addon", confidence="medium")
def login_popup(ctx: AuditContext, emit: Emit) -> None:
    wins = _window_show(ctx)

    def pred(lf: LuaFile, n: Node) -> bool:
        if n.kind == "Call" and call_name(n) == "StaticPopup_Show":
            return True
        if n.kind == "Method" and n.name == "Show" and not n.args:
            k = _key(n.obj)
            return k is not None and k in wins
        return False

    for lf, node in _login_sinks(ctx, pred):
        what = "StaticPopup" if node.kind == "Call" else f"window `{dotted_name(node.obj)}`"
        emit(node.line, f"{what} is shown unconditionally on load/login.", file=lf.rel,
             fix_hint="Guard it with a seen-flag: `if not db.introSeen then ... db.introSeen = true end` "
                      "(or compare `db.lastVersion` for a what's-new note).")


# --------------------------------------------------------------------------- backdrop


def _xml_templates(ctx: AuditContext) -> dict[str, str]:
    out: dict[str, str] = {}
    for xf in ctx.xml_files.values():
        for m in re.finditer(r"<\w+\b([^>]*\bvirtual\s*=\s*\"true\"[^>]*)>", xf.text):
            name = re.search(r"\bname\s*=\s*\"([^\"]+)\"", m.group(1))
            if name:
                inh = re.search(r"\binherits\s*=\s*\"([^\"]+)\"", m.group(1))
                out[name.group(1)] = inh.group(1) if inh else ""
    return out


def _backdrop_guarded(node: Node) -> bool:
    for anc in node.ancestors():
        if anc.kind == "If" and any(re.search(r"SetBackdrop|BackdropTemplate", text_of(c)) for c, _b in anc.clauses):
            return True
        if anc.kind == "BinOp" and anc.op == "and" and "SetBackdrop" in text_of(anc.left):
            return True
    return False


@rule("UX012", "ux", "error", "SetBackdrop on a frame without BackdropTemplate",
      "Since 9.0 (and on Forever / Classic Era) `SetBackdrop` only exists on frames that inherit "
      "`BackdropTemplate`; calling it otherwise errors with `attempt to call method 'SetBackdrop' (a nil value)`.",
      scope="addon", confidence="high")
def backdrop_template(ctx: AuditContext, emit: Emit) -> None:
    xml = _xml_templates(ctx)
    for rec in _frames(ctx):
        sets = [m for m in rec.has("SetBackdrop") if not _backdrop_guarded(m)]
        if not sets or rec.templates is None:
            continue
        if any("Backdrop" in text_of(m) for m in rec.methods if m.name not in ("SetBackdrop",)):
            continue
        tpls = rec.templates
        if any("Backdrop" in t or "Backdrop" in xml.get(t, "") for t in tpls):
            continue
        if rec.var and re.search(r"Mixin\s*\(\s*" + re.escape(rec.var) + r"\s*,\s*BackdropTemplateMixin", rec.lf.src):
            continue
        var = rec.var or "frame"
        if not tpls:
            sev, conf, why = None, None, "was created without a template"
        elif all(t in xml for t in tpls):
            sev, conf, why = None, None, f"inherits `{', '.join(tpls)}` which does not include BackdropTemplate"
        else:
            sev, conf, why = "warn", "medium", f"inherits `{', '.join(tpls)}` (no BackdropTemplate)"
        emit(sets[0].line, f"`{var}:SetBackdrop` but `{var}` {why}; SetBackdrop is nil there.",
             file=rec.lf.rel, severity=sev, confidence=conf,  # type: ignore[arg-type]
             fix_hint=f"Create it with the template: `CreateFrame(\"Frame\", nil, parent, \"BackdropTemplate\")` "
                      f"(append `,BackdropTemplate` to existing templates), or `Mixin({var}, BackdropTemplateMixin)` "
                      "before SetBackdrop.")


# --------------------------------------------------------------------------- strings / fonts


def _has_locale(ctx: AuditContext) -> bool:
    if any(re.match(r"(?i)^(?:.*/)?local(?:e|es|ization)/", lf.rel) for lf in ctx.lua_files()):
        return True
    if re.search(r"AceLocale-3\.0", _all_text(ctx)):
        return True
    n = 0
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for node in lf.ast.walk():
            if (node.kind == "Index" and not node.dot and node.obj.kind == "Name" and node.obj.id == "L"
                    and node.key.kind == "String"):
                n += 1
                if n >= 3:
                    return True
    return False


def _user_sentence(s: str) -> bool:
    plain = _COLOR.sub("", s).strip()
    if "\\" in plain or "/" in plain[:1] or "%" in plain and len(plain) < 12:
        return False
    return bool(_SENTENCE.match(plain)) and len(plain) >= 10


@rule("UX013", "ux", "info", "User-facing text bypasses the locale table",
      "The addon is localised (`L[...]` / Locales/), but some labels and chat lines are hard-coded English, so "
      "translated clients show a mix of languages.", scope="addon", confidence="low")
def hardcoded_strings(ctx: AuditContext, emit: Emit) -> None:
    if not _has_locale(ctx):
        return
    for lf in ctx.parsed_files():
        if re.match(r"(?i)^(?:.*/)?local(?:e|es|ization)/", lf.rel):
            continue
        assert lf.ast is not None
        hits: list[int] = []
        for node, name in iter_calls(lf.ast):
            if name in (":SetText", ":AddLine", ":SetFormattedText") or (_is_print(node) and node.kind == "Call"):
                idx = 0
                if idx < len(node.args) and node.args[idx].kind == "String" and _user_sentence(str(node.args[idx].value)):
                    hits.append(node.line)
        if hits:
            lines = ", ".join(str(n) for n in hits[:5]) + (" ..." if len(hits) > 5 else "")
            emit(hits[0], f"{len(hits)} hard-coded user-facing string(s) bypass `L[...]` (lines {lines}).",
                 file=lf.rel,
                 fix_hint="Use `L[\"Your text\"]` (English key, fallback `L[k] or k`) and add the key to every "
                          "Locales/*.lua file.")


@rule("UX014", "ux", "info", "Hard-coded client font path",
      "Blizzard font files differ per locale (FRIZQT__ has no CJK/Cyrillic glyphs) and ignore the player's UI "
      "font settings; font objects pick the right file automatically.", scope="file", confidence="low")
def hardcoded_font(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    assert lf.ast is not None
    for node, name in iter_calls(lf.ast):
        if name != ":SetFont":
            continue
        path = string_arg(node, 0)
        if path and re.match(r"(?i)^fonts[\\/]", path):
            emit(node.line, f"`SetFont(\"{path}\", ...)` hard-codes a client font file.",
                 fix_hint="Use a font object: `fs:SetFontObject(GameFontNormal)` (or `CreateFontString(nil, "
                          "\"OVERLAY\", \"GameFontHighlight\")`); copy one with `CreateFont` if you need a size.")


# --------------------------------------------------------------------------- Forever templates


def _settings_fallback(node: Node) -> bool:
    """Runs only where the modern ``Settings`` API is missing (else-branch or after an early return)."""
    prev = node
    for anc in node.ancestors():
        if anc.kind == "If":
            first_cond = anc.clauses[0][0]
            if anc.a.get("orelse") is prev and "Settings" in text_of(first_cond):
                return True
            for i, (cond, body) in enumerate(anc.clauses):
                if body is prev:
                    if i > 0 and any("Settings" in text_of(c) for c, _ in anc.clauses[:i]):
                        return True
                    if cond.kind == "UnOp" and cond.op == "not" and "Settings" in text_of(cond):
                        return True
        elif anc.kind == "Block":
            for st in anc.body:
                if _contains(st, node):
                    break
                if (st.kind == "If" and "Settings" in text_of(st.clauses[0][0])
                        and any(s.kind == "Return" for s in st.clauses[0][1].body)):
                    return True
        prev = anc
    return False


@rule("UX015", "ux", "warn", "UICheckButtonTemplate on Forever",
      "On Forever (16001) `UICheckButtonTemplate` broke whole addon windows in this workspace's testing; build the "
      "check button yourself or use the Settings checkbox API.", scope="file", confidence="medium",
      profiles=("forever",))
def forever_checkbutton(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    assert lf.ast is not None
    for node, name in iter_calls(lf.ast):
        if name != "CreateFrame" or node.kind != "Call":
            continue
        tpl = string_arg(node, 3) or ""
        if "UICheckButtonTemplate" not in tpl or _settings_fallback(node):
            continue
        emit(node.line, "`UICheckButtonTemplate` is unreliable on Forever.",
             fix_hint="Use `Settings.CreateCheckbox` on a `Settings.RegisterVerticalLayoutCategory` page, or "
                      "`CreateFrame(\"CheckButton\", nil, parent)` with `SetNormalTexture(\"Interface\\\\Buttons\\\\"
                      "UI-CheckBox-Up\")`, `SetCheckedTexture(\"Interface\\\\Buttons\\\\UI-CheckBox-Check\")` and a "
                      "FontString label.")


# --------------------------------------------------------------------------- tooltips


@rule("UX016", "ux", "warn", "Tooltip shown on enter but never hidden on leave",
      "An OnEnter handler that owns `GameTooltip` without a matching OnLeave `GameTooltip:Hide()` leaves the "
      "tooltip stuck on screen after the mouse moves away.", scope="file", confidence="medium")
def tooltip_no_hide(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    assert lf.ast is not None
    enters: dict[tuple[str, object], list[Node]] = {}
    leaves: dict[tuple[str, object], list[Node]] = {}
    for node in lf.ast.walk():
        if node.kind != "Method" or node.name not in ("SetScript", "HookScript") or len(node.args) < 2:
            continue
        script = string_arg(node, 0)
        k = _key(node.obj)
        if k is None:
            continue
        if script == "OnEnter" and node.name == "SetScript":
            enters.setdefault(k, []).append(node)
        elif script == "OnLeave":
            leaves.setdefault(k, []).append(node)
    for k, nodes in enters.items():
        for node in nodes:
            fn = resolve_function(ctx, lf, node.args[1])
            if fn is None:
                continue
            if not any(c.kind == "Method" and c.name == "SetOwner" and dotted_name(c.obj) == "GameTooltip"
                       for c, _n in iter_calls(fn.body)):
                continue
            ls = leaves.get(k, [])
            if ls:
                ok = False
                for lv in ls:
                    t = _handler_text(ctx, lf, lv.args[1])
                    if t is None or re.search(r"Hide|GameTooltip", t):
                        ok = True
                if ok:
                    continue
            elif k[0] == "G":
                continue  # global (XML / Blizzard) frame: OnLeave may live in XML or the template
            target = dotted_name(node.obj) or "frame"
            emit(node.line, f"`{target}` shows GameTooltip in OnEnter but has no OnLeave that hides it.",
                 fix_hint=f"`{target}:SetScript(\"OnLeave\", GameTooltip_Hide)` (or `function() "
                          "GameTooltip:Hide() end`).")
