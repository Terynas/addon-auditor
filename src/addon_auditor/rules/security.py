"""SECURITY rule pack: dynamic code, taint (replacing Blizzard code), combat lockdown, protected calls,
global namespace hygiene, chat abuse, addon-message validation and secret values.

Vendored libraries (``Libs/``, ``LibFoo.lua``, ``Foo-1.0/``) are skipped: their authors own those findings.
The private helpers below are shared with the SAVEDVARS pack.
"""

from __future__ import annotations

import re
from weakref import WeakKeyDictionary

from ..core.builtins import LUA_GLOBALS
from ..core.context import AuditContext, LuaFile
from ..core.finding import Emit, rule
from ..core.lua_ast import Node, call_name, dotted_name, enclosing_function, string_arg
from ._util import (
    EVENT_NAME,
    event_handler_functions,
    function_table,
    guarded_by,
    resolve_function,
    script_handlers,
    text_of,
)

# --------------------------------------------------------------------------- shared helpers

_LIB_DIR = re.compile(r"(^|/)(libs?|librar(?:y|ies)|embeds?|vendor|externals?)/", re.I)
_LIB_FILE = re.compile(r"(^|/)(LibStub|CallbackHandler[^/]*|Ace[A-Z][^/]*|Lib[A-Z][^/]*)\.lua$|-\d+\.\d+/")


def _is_lib(rel: str) -> bool:
    return bool(_LIB_DIR.search(rel) or _LIB_FILE.search(rel))


def _own_files(ctx: AuditContext) -> list[LuaFile]:
    return [lf for lf in ctx.parsed_files() if not _is_lib(lf.rel)]


def _nodes(ctx: AuditContext, lf: LuaFile, *kinds: str) -> list[Node]:
    """Nodes of the given kinds in ``lf`` (source pre-order per kind), from a per-file index built once."""
    cache = ctx.__dict__.setdefault("_sec_index", {})
    idx = cache.get(lf.rel)
    if idx is None:
        idx = {}
        assert lf.ast is not None
        for n in lf.ast.walk():
            idx.setdefault(n.kind, []).append(n)
        cache[lf.rel] = idx
    if len(kinds) == 1:
        return idx.get(kinds[0], [])
    return [n for k in kinds for n in idx.get(k, [])]


def _calls(ctx: AuditContext, lf: LuaFile) -> list[tuple[Node, str]]:
    out = []
    for n in _nodes(ctx, lf, "Call", "Method"):
        name = call_name(n)
        if name:
            out.append((n, name))
    return out


def _contains(outer: Node, inner: Node) -> bool:
    return outer is inner or any(a is outer for a in inner.ancestors())


def _exits(block: Node) -> bool:
    return any(st.kind in ("Return", "Break") for st in block.body)


_LOCAL_VALUES: WeakKeyDictionary[Node, Node | None] = WeakKeyDictionary()


def _local_value(decl: Node | None) -> Node | None:
    """Initial value of ``local x = <value>`` when ``x`` is never reassigned."""
    if decl is None or decl.parent is None or decl.parent.kind != "Local":
        return None
    try:
        return _LOCAL_VALUES[decl]
    except KeyError:
        pass
    val: Node | None = None
    if not any(r.a.get("is_write") for r in decl.a.get("refs", [])):
        loc = decl.parent
        idx = next((i for i, n in enumerate(loc.names) if n is decl), -1)
        val = loc.values[idx] if 0 <= idx < len(loc.values) else None
    _LOCAL_VALUES[decl] = val
    return val


def _g_index(expr: Node) -> str | None:
    """``_G.X`` / ``_G["X"]`` -> ``X``."""
    if expr.kind == "Index" and expr.key.kind == "String":
        obj = expr.obj
        if obj.kind == "Name" and obj.id == "_G" and obj.a.get("is_global"):
            return str(expr.key.value)
    return None


def _global_ref(expr: Node | None) -> str | None:
    """Global the expression denotes: ``X``, ``_G.X``, ``_G["X"]`` or a never-reassigned ``local x = X``."""
    if expr is None:
        return None
    if expr.kind == "Paren":
        return _global_ref(expr.expr)
    if expr.kind == "Name":
        if expr.a.get("is_global"):
            return expr.id
        val = _local_value(expr.a.get("decl"))
        if val is not None and val.kind in ("Name", "Index"):
            if val.kind == "Name":
                return val.id if val.a.get("is_global") else None
            return _g_index(val)
        return None
    if expr.kind == "Index":
        return _g_index(expr)
    return None


# Entries in the bundled API data that are annotation artefacts or embeddable libraries, not client globals.
_API_ARTIFACTS = frozenset({"Frame", "Button", "lib", "xx", "arg", "RG", "PI"})


def _client_global(ctx: AuditContext, name: str) -> bool:
    if name in LUA_GLOBALS or name in _API_ARTIFACTS or name.startswith(("Lib", "Ace")) or name == "CallbackHandler":
        return False
    return any(ctx.api.global_in(name).values())


_FRAMEXML_FUNC = re.compile(
    r"^(?:ChatFrame|ChatEdit|FCF|GameTooltip|ItemRefTooltip|UnitFrame|PlayerFrame|TargetFrame|FocusFrame|"
    r"PartyMemberFrame|CompactUnitFrame|CompactRaidFrame|ActionButton|PaperDollFrame|PaperDollItemSlotButton|"
    r"ContainerFrame|BankFrame|MerchantFrame|QuestLog|QuestFrame|WorldMapFrame|Minimap|StaticPopup|UIParent|"
    r"UIDropDownMenu|SpellBook|SpellButton|LootFrame|MailFrame|OpenMail|SendMail|TradeSkillFrame|"
    r"CastingBarFrame|BuffFrame|AuraButton|TextStatusBar|NamePlate|PetActionBar|MultiActionBar|MainMenuBar|"
    r"CharacterFrame|InterfaceOptions|InterfaceOptionsFrame|AuctionFrame|GuildFrame|FriendsFrame|LFGList|"
    r"PVEFrame|ClassTalent|EditModeManager)_[A-Za-z]")
_FRAMEXML_EXACT = frozenset({"SetItemRef", "ShowUIPanel", "HideUIPanel", "ToggleDropDownMenu", "CloseDropDownMenus",
                             "CloseSpecialWindows", "ToggleGameMenu", "SecureCmdOptionParse"})
_BLIZZ_FRAME = re.compile(
    r"^(?:ChatFrame\d+(?:EditBox|Tab)?|WorldFrame|UIParent|GameTooltip|ItemRefTooltip|ShoppingTooltip\d|Minimap|"
    r"MinimapCluster|PlayerFrame|TargetFrame|FocusFrame|PartyMemberFrame\d|CompactRaidFrameContainer|MainMenuBar|"
    r"MultiBar\w+|ActionButton\d+|CharacterFrame|SpellBookFrame|WorldMapFrame|QuestLogFrame|ContainerFrame\d+|"
    r"MerchantFrame|MailFrame|LootFrame|StaticPopup\d|GameMenuFrame|DEFAULT_CHAT_FRAME|UIErrorsFrame|"
    r"RaidWarningFrame|ObjectiveTrackerFrame|QuestWatchFrame|BuffFrame|DebuffFrame|CastingBarFrame|"
    r"PlayerCastingBarFrame|NamePlateDriverFrame)$")
# Blizzard tables addons are *meant* to add entries to.
_REGISTRIES = frozenset({"SlashCmdList", "StaticPopupDialogs", "UISpecialFrames", "CUSTOM_CLASS_COLORS",
                         "UIPanelWindows", "UIMenus", "ChatTypeInfo", "RAID_CLASS_COLORS", "ITEM_QUALITY_COLORS"})


def _created_names(ctx: AuditContext) -> set[str]:
    """Global frame names the addon creates (``CreateFrame(type, "Name")`` and XML ``name=``)."""
    cached = getattr(ctx, "_sec_created", None)
    if cached is not None:
        return cached
    names = set(ctx.xml_global_names)
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for node, name in _calls(ctx, lf):
            if name == "CreateFrame":
                s = string_arg(node, 1)
                if s and "$" not in s:
                    names.add(s)
    ctx._sec_created = names  # type: ignore[attr-defined]
    return names


def _blizzard_frame(ctx: AuditContext, name: str) -> bool:
    if name in _REGISTRIES:
        return False
    if _client_global(ctx, name) or _BLIZZ_FRAME.match(name):
        return True  # even if the addon also (wrongly) creates/assigns it: SEC005/SEC002 report that part
    return False


# ---- event-handler context


_ONE_SHOT_EVENTS = frozenset({"ADDON_LOADED", "PLAYER_LOGIN", "VARIABLES_LOADED", "PLAYER_LOGOUT"})
# Secure frames may still be configured while these run (login, or just before/after combat).
_COMBAT_SAFE_EVENTS = _ONE_SHOT_EVENTS | {"PLAYER_REGEN_ENABLED", "PLAYER_REGEN_DISABLED", "PLAYER_ENTERING_WORLD"}


def _event_literals(cond: Node, op: str) -> set[str]:
    out: set[str] = set()
    for n in cond.walk():
        if n.kind == "BinOp" and n.op == op:
            for side in (n.left, n.right):
                if side.kind == "String" and EVENT_NAME.match(str(side.value)):
                    out.add(str(side.value))
    return out


def _narrow(node: Node, fn: Node, events: set[str]) -> set[str]:
    """Events for which ``node`` (inside handler ``fn``) can run, using ``if event == "X"`` branches and
    ``if event ~= "X" then return end`` early exits."""
    result = set(events)
    cur = node
    for anc in node.ancestors():
        if anc is fn:
            break
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if body is cur:
                    lits = _event_literals(cond, "==")
                    if lits:
                        result = (result & lits) or lits
                    break
        elif anc.kind == "Block":
            for st in anc.body:
                if st is cur:
                    break
                if st.kind == "If" and _exits(st.clauses[0][1]):
                    lits = _event_literals(st.clauses[0][0], "~=")
                    if lits:
                        result = (result & lits) or lits
        cur = anc
    return result


def _fn_files(ctx: AuditContext) -> dict[int, LuaFile]:
    cached = getattr(ctx, "_sec_fn_files", None)
    if cached is not None:
        return cached
    out: dict[int, LuaFile] = {}
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for n in _nodes(ctx, lf, "Function"):
            if n.kind == "Function":
                out[id(n)] = lf
    ctx._sec_fn_files = out  # type: ignore[attr-defined]
    return out


def _resolve_callee(ctx: AuditContext, lf: LuaFile, call: Node) -> Node | None:
    if call.kind == "Call":
        return resolve_function(ctx, lf, call.func)
    if call.kind == "Method":
        base = dotted_name(call.obj)
        if base and base != "self":
            return function_table(ctx).get(f"{base}:{call.name}")
    return None


def _handler_map(ctx: AuditContext, skip_guarded: bool = False) -> dict[int, set[str]]:
    """id(Function) -> events it may run for: event handlers plus functions they call directly.

    With ``skip_guarded`` call sites behind an ``InCombatLockdown()`` check do not propagate."""
    key = f"_sec_handlers_{skip_guarded}"
    cached = getattr(ctx, key, None)
    if cached is not None:
        return cached
    base = event_handler_functions(ctx)
    out: dict[int, set[str]] = {fid: set(evs) for fid, (_fn, evs) in base.items()}
    files = _fn_files(ctx)
    for fid, (fn, evs) in base.items():
        lf = files.get(fid)
        if lf is None:
            continue
        for call in fn.body.walk():
            if call.kind not in ("Call", "Method") or enclosing_function(call) is not fn:
                continue
            if skip_guarded and _combat_guarded(call):
                continue
            callee = _resolve_callee(ctx, lf, call)
            if callee is None or callee is fn or id(callee) in base:
                continue
            out.setdefault(id(callee), set()).update(_narrow(call, fn, evs))
    setattr(ctx, key, out)
    return out


def _events_at(ctx: AuditContext, node: Node, skip_guarded: bool = False) -> set[str] | None:
    """Events the code at ``node`` runs for, or None when it is not (directly) in an event handler."""
    fn = enclosing_function(node)
    if fn is None:
        return None
    evs = _handler_map(ctx, skip_guarded).get(id(fn))
    return None if evs is None else _narrow(node, fn, evs)


def _onupdate_fns(ctx: AuditContext) -> set[int]:
    cached = getattr(ctx, "_sec_onupdate", None)
    if cached is not None:
        return cached
    out = {id(h.func) for lf in ctx.parsed_files() for h in script_handlers(ctx, lf, {"OnUpdate"})
           if h.func is not None}
    ctx._sec_onupdate = out  # type: ignore[attr-defined]
    return out


def _mentions_combat(cond: Node) -> bool:
    t = text_of(cond).lower()
    return "combat" in t or "lockdown" in t


def _combat_guarded(node: Node) -> bool:
    """Behind ``if not InCombatLockdown()``/``UnitAffectingCombat`` (or after an early return on it)."""
    cur = node
    for anc in node.ancestors():
        if anc.kind == "If":
            for cond, body in anc.clauses:
                if body is cur and _mentions_combat(cond):
                    return True
            if anc.a.get("orelse") is cur and any(_mentions_combat(c) for c, _ in anc.clauses):
                return True
        elif anc.kind == "BinOp" and anc.op in ("and", "or") and anc.right is cur and _mentions_combat(anc.left):
            return True
        elif anc.kind == "Block":
            for st in anc.body:
                if st is cur:
                    break
                if st.kind == "If" and _mentions_combat(st.clauses[0][0]) and _exits(st.clauses[0][1]):
                    return True
        cur = anc
    return False


# ---- SavedVariables roots (shared with the savedvars pack)


def _direct_sv(val: Node | None, svs: set[str]) -> str | None:
    if val is None:
        return None
    if val.kind == "BinOp" and val.op == "or":
        val = val.left
    if val.kind == "Name" and val.a.get("is_global") and val.id in svs:
        return val.id
    return None


def _sv_aliases(ctx: AuditContext) -> dict[str, str]:
    """Dotted names consistently assigned a SavedVariables table (``ns.db = MyAddonDB``) -> SV name."""
    cached = getattr(ctx, "_sec_sv_alias", None)
    if cached is not None:
        return cached
    svs = set(ctx.addon.saved_variables)
    cand: dict[str, set[str | None]] = {}
    if svs:
        for lf in _own_files(ctx):
            assert lf.ast is not None
            for node in _nodes(ctx, lf, "Assign"):
                if node.kind != "Assign":
                    continue
                for i, tg in enumerate(node.targets):
                    dn = dotted_name(tg)
                    if not dn or "." not in dn or dn.startswith("self."):
                        continue
                    val = node.values[i] if i < len(node.values) else None
                    cand.setdefault(dn, set()).add(_direct_sv(val, svs))
    out = {dn: next(iter(s)) for dn, s in cand.items() if len(s) == 1 and None not in s}
    ctx._sec_sv_alias = out  # type: ignore[attr-defined]
    return out  # type: ignore[return-value]


def _sv_set(ctx: AuditContext) -> frozenset[str]:
    cached = getattr(ctx, "_sec_svs", None)
    if cached is None:
        cached = frozenset(ctx.addon.saved_variables)
        ctx._sec_svs = cached  # type: ignore[attr-defined]
    return cached


def _sv_root(ctx: AuditContext, expr: Node | None, depth: int = 0) -> str | None:
    """SavedVariable a table expression lives in (``MyDB``, ``MyDB.x[k]``, ``ns.db.y``, ``local db = MyDB``)."""
    svs = _sv_set(ctx)
    if not svs:
        return None
    aliases = _sv_aliases(ctx)
    cur = expr
    while cur is not None and depth < 4:
        if cur.kind == "Name":
            if cur.a.get("is_global"):
                return cur.id if cur.id in svs else None
            val = _local_value(cur.a.get("decl"))
            cur, depth = val, depth + 1
            continue
        if cur.kind == "Index":
            dn = dotted_name(cur)
            if dn and dn in aliases:
                return aliases[dn]
            cur = cur.obj
            continue
        if cur.kind == "BinOp" and cur.op == "or":
            cur = cur.left
            continue
        if cur.kind == "Paren":
            cur = cur.expr
            continue
        return None
    return None


def _sv_target(ctx: AuditContext, tg: Node) -> str | None:
    """SV written by assignment target ``tg`` (the SV global itself or a field below it)."""
    if tg.kind == "Name":
        return tg.id if tg.a.get("is_global") and tg.id in _sv_set(ctx) else None
    if tg.kind == "Index":
        return _sv_root(ctx, tg.obj)
    return None


# --------------------------------------------------------------------------- SEC001

_EXEC_FUNCS = frozenset({"loadstring", "load", "RunScript"})


def _is_constant(e: Node, depth: int = 0) -> bool:
    if e.kind in ("String", "Number"):
        return True
    if e.kind == "Paren":
        return _is_constant(e.expr, depth)
    if e.kind == "BinOp" and e.op == "..":
        return _is_constant(e.left, depth) and _is_constant(e.right, depth)
    if e.kind == "Name" and not e.a.get("is_global") and depth < 3:
        val = _local_value(e.a.get("decl"))
        return val is not None and _is_constant(val, depth + 1)
    return False


def _shipped_strings(ctx: AuditContext) -> set[str]:
    """Dotted names the addon only ever assigns string literals (code/data shipped inside the addon)."""
    cached = getattr(ctx, "_sec_shipped", None)
    if cached is not None:
        return cached
    seen: dict[str, bool] = {}
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for node in _nodes(ctx, lf, "Assign"):
            if node.kind != "Assign":
                continue
            for i, tg in enumerate(node.targets):
                dn = dotted_name(tg)
                if dn and "." in dn:
                    val = node.values[i] if i < len(node.values) else None
                    ok = val is not None and _is_constant(val)
                    seen[dn] = seen.get(dn, True) and ok
    out = {dn for dn, ok in seen.items() if ok}
    ctx._sec_shipped = out  # type: ignore[attr-defined]
    return out


def _untrusted_source(ctx: AuditContext, arg: Node, depth: int = 0) -> str | None:
    svs = set(ctx.addon.saved_variables)
    for n in arg.walk():
        if n.kind == "Name" and n.a.get("is_global") and n.id in svs:
            return f"SavedVariables data (`{n.id}`)"
        if n.kind == "Method" and n.name == "GetText":
            return "EditBox text"
        if n.kind == "Name" and not n.a.get("is_global") and depth < 2:
            val = _local_value(n.a.get("decl"))
            if val is not None:
                src = _untrusted_source(ctx, val, depth + 1)
                if src:
                    return src
    evs = _events_at(ctx, arg)
    if evs and any(e.startswith("CHAT_MSG") for e in evs):
        ev = "CHAT_MSG_ADDON" if "CHAT_MSG_ADDON" in evs else sorted(e for e in evs if e.startswith("CHAT_MSG"))[0]
        return f"a {ev} payload"
    return None


@rule("SEC001", "security", "error", "Dynamic code execution (loadstring / RunScript)",
      "`loadstring`, `load` or `RunScript` on a non-constant string runs whatever that string contains with the "
      "player's full UI privileges. Data from chat, addon messages, EditBoxes or SavedVariables can be crafted.",
      tags=("taint",))
def dynamic_code(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    if _is_lib(lf.rel):
        return
    assert lf.ast is not None
    for node in _nodes(ctx, lf, "Call"):
        if node.kind != "Call":
            continue
        fname = _global_ref(node.func)
        arg_i = 0
        if fname in ("pcall", "xpcall") and node.args:
            inner = _global_ref(node.args[0])
            if inner not in _EXEC_FUNCS:
                continue
            fname, arg_i = inner, 1
        if fname not in _EXEC_FUNCS or len(node.args) <= arg_i:
            continue
        arg = node.args[arg_i]
        tag = [f"symbol:{fname}"]
        if _is_constant(arg) or dotted_name(arg) in _shipped_strings(ctx):
            emit(node.line, f"`{fname}` on a string shipped with the addon: the code is fixed, so compiling it at "
                            "runtime only adds cost and hides it from linters.", severity="info", tags=tag,
                 fix_hint="Write the code as a normal Lua function instead of a string.")
            continue
        src = _untrusted_source(ctx, arg)
        what = src or "a runtime string"
        emit(node.line, f"`{fname}` executes {what} as code: anyone who can shape that string runs arbitrary Lua "
                        "in this UI session.", confidence="high" if src else "medium", tags=tag,
             fix_hint="Parse the data into plain values instead (e.g. `msg:match(\"^(%d+):(.+)$\")`, a lookup "
                      "table of allowed commands), validate every field, and never compile received or saved text.")


# --------------------------------------------------------------------------- SEC002

_METHODISH = re.compile(r"^(?:On[A-Z]|(?:Set|Get|Add|Show|Hide|Clear|Update|Is|Has|Enable|Disable|Register|"
                        r"Unregister|Toggle|Refresh)(?:[A-Z]|$))")


def _blizzard_function_kind(ctx: AuditContext, name: str) -> str | None:
    if name.startswith(("SLASH_", "BINDING_")) or name in ctx.addon.saved_variables:
        return None
    if name in _created_names(ctx):
        return None
    if _client_global(ctx, name):
        return "api"
    if name in _FRAMEXML_EXACT or _FRAMEXML_FUNC.match(name):
        return "pattern"
    return None


def _is_polyfill(stmt: Node, val: Node | None, names: tuple[str, ...]) -> bool:
    if val is not None and val.kind == "BinOp" and val.op == "or":
        left = val.left
        if (left.kind == "Name" and left.id in names) or _g_index(left) in names:
            return True
    return any(guarded_by(stmt, n) for n in names)


@rule("SEC002", "security", "error", "Replacing a Blizzard function or global",
      "Assigning over a client API, FrameXML function or a Blizzard object's method changes it for the whole UI "
      "and taints every secure code path that calls it (ADDON_ACTION_BLOCKED, broken action bars).",
      tags=("taint",))
def replace_blizzard(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    if _is_lib(lf.rel):
        return
    assert lf.ast is not None
    for node in _nodes(ctx, lf, "Assign", "FunctionDecl"):
        pairs: list[tuple[Node, Node | None]] = []
        if node.kind == "Assign":
            pairs = [(tg, node.values[i] if i < len(node.values) else None) for i, tg in enumerate(node.targets)]
        elif node.kind == "FunctionDecl":
            pairs = [(node.target, node.func)]
        for tg, val in pairs:
            _check_replacement(ctx, emit, node, tg, val)


def _is_function_value(ctx: AuditContext, val: Node | None) -> bool:
    if val is None:
        return False
    if val.kind == "Function":
        return True
    if val.kind in ("Name", "Index"):
        dn = dotted_name(val)
        if dn and dn in function_table(ctx):
            return True
        if val.kind == "Name" and not val.a.get("is_global"):
            local = _local_value(val.a.get("decl"))
            return local is not None and local.kind == "Function"
    return False


def _check_replacement(ctx: AuditContext, emit: Emit, stmt: Node, tg: Node, val: Node | None) -> None:
    is_fn = _is_function_value(ctx, val)
    name: str | None = None
    if tg.kind == "Name" and tg.a.get("is_global"):
        name = tg.id
    elif tg.kind == "Index":
        name = _g_index(tg)
        if name is None:
            _check_method_replacement(ctx, emit, stmt, tg, is_fn)
            return
    if name is None:
        return
    kind = _blizzard_function_kind(ctx, name)
    if kind is None or (kind == "pattern" and not is_fn):
        return
    if _is_polyfill(stmt, val, (name, f"_G.{name}")):
        return
    if is_fn or kind == "pattern":
        msg = (f"Replaces Blizzard function `{name}`: every caller (including secure FrameXML) now runs addon code "
               "and becomes tainted.")
        hint = (f"Post-hook it: `hooksecurefunc(\"{name}\", function(...) ... end)`. To filter chat use "
                "`ChatFrame_AddMessageEventFilter`; for tooltips use `TooltipDataProcessor`/`HookScript`.")
    else:
        msg = (f"Overwrites Blizzard global `{name}`: Blizzard code that reads it now reads a tainted value, and "
               "other addons lose the original.")
        hint = (f"Keep your own value in a local or your addon namespace (e.g. `ns.{name}`); read `{name}` but "
                "never assign it.")
    emit(stmt.line, msg, confidence="high" if kind == "api" and is_fn else "medium", fix_hint=hint,
         tags=[f"symbol:{name}"])


def _check_method_replacement(ctx: AuditContext, emit: Emit, stmt: Node, tg: Node, is_fn: bool) -> None:
    if not is_fn or tg.key.kind != "String" or tg.obj.kind != "Name" or not tg.obj.a.get("is_global"):
        return
    owner, key = tg.obj.id, str(tg.key.value)
    if owner == "_G" or not _blizzard_frame(ctx, owner):
        return
    known_member = any(ctx.api.member_in(owner, key).values())
    if not known_member and not _METHODISH.match(key):
        return
    hint = (f"Use `hooksecurefunc({owner}, \"{key}\", function(self, ...) ... end)` to run after it"
            + (f", or `{owner}:HookScript(\"{key}\", fn)` for a script handler." if key.startswith("On") else "."))
    emit(stmt.line, f"Replaces method `{owner}.{key}` on a Blizzard object: secure code calling it is tainted and "
                    "the original behaviour is lost for every addon.",
         confidence="high" if known_member else "medium", fix_hint=hint, tags=[f"symbol:{key}"])


# --------------------------------------------------------------------------- SEC003


def _frame_root(obj: Node) -> tuple[str, str] | None:
    """(global root name, display) for ``GameTooltip``, ``_G.ChatFrame1``, ``PlayerFrame.healthbar``,
    or a ``local tt = GameTooltip`` alias. None for calls, ``self`` and other locals."""
    g = _global_ref(obj)
    if g is not None:
        return g, g
    cur = obj
    while cur.kind == "Index":
        cur = cur.obj
    if cur.kind == "Name":
        root = _global_ref(cur)
        if root is not None:
            return root, dotted_name(obj) or root
    return None


@rule("SEC003", "security", "error", "SetScript on a Blizzard frame",
      "`SetScript` replaces the handler Blizzard installed (and any other addon's), breaking default behaviour "
      "and tainting the frame. `HookScript` runs your code after the original instead.", tags=("taint",))
def setscript_blizzard(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    if _is_lib(lf.rel):
        return
    assert lf.ast is not None
    for node in _nodes(ctx, lf, "Method"):
        if node.kind != "Method" or node.name != "SetScript" or not node.args:
            continue
        found = _frame_root(node.obj)
        if found is None or not _blizzard_frame(ctx, found[0]):
            continue
        root, shown = found
        script = string_arg(node, 0) or "<script>"
        emit(node.line, f"`{shown}:SetScript(\"{script}\", ...)` replaces Blizzard's own {script} handler on a frame "
                        "this addon does not own.",
             fix_hint=f"Use `{shown}:HookScript(\"{script}\", function(self, ...) ... end)` (runs after the "
                      "original); never pass nil to clear a Blizzard handler.",
             tags=[f"symbol:{root}"])


# --------------------------------------------------------------------------- SEC004

_SECURE_METHODS = frozenset({"SetAttribute", "Show", "Hide", "SetPoint", "ClearAllPoints", "SetAllPoints",
                             "SetParent", "SetSize", "SetWidth", "SetHeight", "SetScale", "SetFrameRef"})
_COMBAT_LOCKED_FUNCS = frozenset({
    "RegisterStateDriver", "UnregisterStateDriver", "RegisterAttributeDriver", "UnregisterAttributeDriver",
    "RegisterUnitWatch", "UnregisterUnitWatch", "SetBinding", "SetBindingClick", "SetBindingSpell",
    "SetBindingItem", "SetBindingMacro", "SetOverrideBinding", "SetOverrideBindingClick",
    "SetOverrideBindingSpell", "SetOverrideBindingItem", "SetOverrideBindingMacro", "ClearOverrideBindings",
})


def _secure_frames(ctx: AuditContext, lf: LuaFile) -> tuple[set[int], set[str]]:
    """Locals (by declaration id) and dotted/global names holding frames built from a Secure* template."""
    decls: set[int] = set()
    names: set[str] = set()
    assert lf.ast is not None
    for node in _nodes(ctx, lf, "Call"):
        if node.kind != "Call" or _global_ref(node.func) != "CreateFrame":
            continue
        tmpl = string_arg(node, 3)
        if not tmpl or "Secure" not in tmpl:
            continue
        gname = string_arg(node, 1)
        if gname and "$" not in gname:
            names.add(gname)
        p = node.parent
        if p is None:
            continue
        if p.kind == "Local":
            idx = next((i for i, v in enumerate(p.values) if v is node), -1)
            if 0 <= idx < len(p.names):
                decls.add(id(p.names[idx]))
        elif p.kind == "Assign":
            idx = next((i for i, v in enumerate(p.values) if v is node), -1)
            if 0 <= idx < len(p.targets):
                tg = p.targets[idx]
                if tg.kind == "Name" and tg.a.get("decl") is not None:
                    decls.add(id(tg.a["decl"]))
                dn = dotted_name(tg)
                if dn and not dn.startswith("self."):
                    names.add(dn)
    return decls, names


def _is_secure_obj(obj: Node, decls: set[int], names: set[str]) -> bool:
    if obj.kind == "Name" and not obj.a.get("is_global"):
        decl = obj.a.get("decl")
        return decl is not None and id(decl) in decls
    dn = dotted_name(obj) or _g_index(obj)
    return dn is not None and dn in names


@rule("SEC004", "security", "warn", "Combat-locked operation without InCombatLockdown() check",
      "Secure frames (Secure*Template) cannot be shown, hidden, moved or have attributes changed in combat, and "
      "bindings/state drivers cannot change either. Event handlers can run mid-combat, so the call is blocked "
      "(ADDON_ACTION_BLOCKED) and the addon is blamed.", confidence="medium", tags=("taint", "combat"))
def combat_lockdown(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    if _is_lib(lf.rel):
        return
    assert lf.ast is not None
    decls, names = _secure_frames(ctx, lf)
    for node, name in _calls(ctx, lf):
        if node.kind == "Method":
            if node.name not in _SECURE_METHODS or not _is_secure_obj(node.obj, decls, names):
                continue
            what = f"`{dotted_name(node.obj) or 'frame'}:{node.name}()` on a secure frame"
        else:
            gname = _global_ref(node.func)
            if gname not in _COMBAT_LOCKED_FUNCS:
                continue
            what = f"`{gname}()`"
            name = gname
        evs = _events_at(ctx, node, skip_guarded=True)
        if evs is None or not evs or evs <= _COMBAT_SAFE_EVENTS or _combat_guarded(node):
            continue
        risky = sorted(evs - _COMBAT_SAFE_EVENTS)
        shown = ", ".join(risky[:3]) + (", ..." if len(risky) > 3 else "")
        emit(node.line, f"{what} runs from an event handler ({shown}) with no InCombatLockdown() check; in combat "
                        "it is blocked and the addon is blamed.",
             fix_hint="`if InCombatLockdown() then pending = true; f:RegisterEvent(\"PLAYER_REGEN_ENABLED\") "
                      "return end`, then apply the change from the PLAYER_REGEN_ENABLED handler.",
             tags=[f"symbol:{name.lstrip(':')}"])


# --------------------------------------------------------------------------- SEC005

_GENERIC_NAMES = frozenset({
    "frame", "f", "db", "l", "config", "cfg", "options", "opts", "settings", "debug", "data", "core", "main",
    "addon", "ui", "utils", "util", "helper", "helpers", "log", "logger", "defaults", "default", "init", "setup",
    "update", "button", "btn", "panel", "window", "menu", "list", "cache", "temp", "tmp", "test", "event",
    "events", "handler", "handlers", "timer", "ticker", "tooltip", "locale", "lang", "version", "name", "player",
    "target", "count", "index", "value", "result", "color", "colors", "font", "icon", "str", "num", "api",
    "module", "modules", "ns", "private", "mod", "toggle", "enabled", "state", "status", "info", "item", "items",
    "spell", "spells", "unit", "units", "profile", "char", "callback", "callbacks", "slash", "minimap",
    "minimapbutton", "mainframe", "optionsframe", "configframe", "eventframe", "loader", "start", "run",
})
_EXEMPT_GLOBAL = re.compile(r"^(?:SLASH_|BINDING_)")
_SV_SUFFIX = re.compile(r"(?:DB|Db|Data|Settings|Config|Vars|SV|Saved|Options|PerChar|Char|Global|Store)+$")
_XML_NAMED = re.compile(r"<(\w+)\b([^>]*?)\bname\s*=\s*\"([A-Za-z_][A-Za-z0-9_]*)\"([^>]*)>")


def _abbrev(name: str) -> str:
    alnum = re.sub(r"[^A-Za-z0-9]", "", name)
    return "".join(c for c in alnum if c.isupper() or c.isdigit())


def _own_prefixes(ctx: AuditContext, own_globals: dict[str, tuple[str, Node]]) -> set[str]:
    bases = [ctx.addon.name]
    for t in ctx.addon.tocs:
        title = t.get("Title")
        if title:
            bases.append(re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", title))
    for sv in ctx.addon.saved_variables:
        base = _SV_SUFFIX.sub("", sv)
        if len(base) >= 3:
            bases.append(base)
    out: set[str] = set()
    for b in bases:
        alnum = re.sub(r"[^A-Za-z0-9]", "", b)
        if len(alnum) >= 2:
            out.add(alnum.lower())
        ab = _abbrev(b)
        if len(ab) >= 2:
            out.add(ab.lower())
        # Parts and leading CamelCase words: "Details_Streamer" -> details, streamer;
        # "AtlasLootClassic" -> atlasloot.
        for part in re.split(r"[_\-\s.]+", b):
            words = re.findall(r"[A-Z]+[a-z0-9]*|[a-z0-9]+", part)
            if len(part) >= 4:
                out.add(part.lower())
            for k in range(1, len(words)):
                lead = "".join(words[:k])
                if k >= 2 or len(lead) >= 5:
                    out.add(lead.lower())
    # The addon's own namespace tables (`MyAddon = MyAddon or {}`, `PM = {}`) also count as prefixes.
    for name, (_file, node) in own_globals.items():
        p = node.parent
        if p is not None and p.kind == "Assign" and len(name) >= 2 and name.lower() not in _GENERIC_NAMES:
            idx = next((i for i, t in enumerate(p.targets) if t is node), -1)
            val = p.values[idx] if 0 <= idx < len(p.values) else None
            if val is not None and (val.kind == "Table" or (val.kind == "BinOp" and val.op == "or")):
                out.add(name.lower())
    return out


def _is_generic(name: str) -> bool:
    return len(name) <= 3 or name.lower() in _GENERIC_NAMES


@rule("SEC005", "security", "warn", "Generic or colliding global name",
      "Every addon shares one global namespace. Short or generic globals (`db`, `L`, `frame`, `Config`) and frame "
      "names collide with other addons, and reusing a Blizzard name replaces the default UI's object.",
      scope="addon", tags=("taint",))
def global_hygiene(ctx: AuditContext, emit: Emit) -> None:
    svs = set(ctx.addon.saved_variables)
    own_globals: dict[str, tuple[str, Node]] = {}
    for name, sites in ctx.addon_globals.items():
        for rel, node in sorted(sites, key=lambda s: (s[0], s[1].line)):
            if not _is_lib(rel):
                own_globals.setdefault(name, (rel, node))
                break
    prefixes = _own_prefixes(ctx, own_globals)

    def exempt(name: str) -> bool:
        return name in svs or bool(_EXEMPT_GLOBAL.match(name)) or name in _REGISTRIES or name.startswith("_")

    def prefixed(name: str) -> bool:
        low = name.lower()
        return any(low.startswith(p) for p in prefixes)

    # Lua globals: unprefixed ones are already LINT003; here only generic names (which collide in practice).
    for name, (rel, node) in sorted(own_globals.items()):
        if exempt(name) or _client_global(ctx, name) or _blizzard_function_kind(ctx, name):
            continue  # Blizzard names: SEC002
        if _is_generic(name) and not prefixed(name):
            emit(node.line, f"Global `{name}` is too generic: any other addon using the same name overwrites it "
                            "(or you overwrite theirs).", file=rel, tags=[f"symbol:{name}"],
                 fix_hint=f"Make it `local {name}`, or keep it on your addon namespace (`local _, ns = ...; "
                          f"ns.{name} = ...`). Globals that must exist need an addon prefix "
                          f"(`{ctx.addon.name}_{name}`).")

    # Frame names from CreateFrame / XML (LINT003 cannot see these).
    frames: dict[str, tuple[str, int]] = {}
    for lf in _own_files(ctx):
        assert lf.ast is not None
        for node, cname in _calls(ctx, lf):
            if node.kind == "Call" and _global_ref(node.func) == "CreateFrame" and cname:
                s = string_arg(node, 1)
                if s and "$" not in s:
                    frames.setdefault(s, (lf.rel, node.line))
    for rel, xf in ctx.xml_files.items():
        if _is_lib(rel):
            continue
        for m in _XML_NAMED.finditer(xf.text):
            tag, before, fname, after = m.groups()
            if tag in ("Attribute", "Include", "Script", "KeyValue") or "virtual=\"true\"" in before + after:
                continue
            frames.setdefault(fname, (rel, xf.text.count("\n", 0, m.start()) + 1))
    for fname, (rel, line) in sorted(frames.items()):
        if exempt(fname):
            continue
        if _client_global(ctx, fname) or _BLIZZ_FRAME.match(fname):
            emit(line, f"Frame name `{fname}` is already a Blizzard global: creating it replaces the default UI's "
                       "object for every addon and taints code that uses it.", file=rel, severity="error",
                 tags=[f"symbol:{fname}"],
                 fix_hint=f"Rename it with your addon prefix (`{ctx.addon.name}{fname}`), or pass nil as the name "
                          "if nothing needs to look it up globally.")
        elif not prefixed(fname):
            emit(line, f"Frame name `{fname}` becomes a global without an addon prefix; another addon creating the "
                       "same name silently replaces it.", file=rel, tags=[f"symbol:{fname}"],
                 confidence="high" if _is_generic(fname) else "medium",
                 fix_hint=f"Prefix it (`{ctx.addon.name}{fname}`) or pass nil as the frame name and keep a local "
                          "reference.")


# --------------------------------------------------------------------------- SEC006

_THROTTLE_TOKENS = ("throttle", "cooldown", "lastsent", "last_sent", "lastsend", "ratelimit", "rate_limit",
                    "elapsed", "c_timer", "nextsend", "next_send", "lastannounce", "lastmsg", "last_msg")
_TIME_FUNCS = frozenset({"GetTime", "time", "GetServerTime", "GetTimePreciseSec", "debugprofilestop"})


def _throttled(node: Node) -> bool:
    for fn in (a for a in node.ancestors() if a.kind == "Function"):
        for n in fn.walk():
            if n.kind == "Name" and n.id in _TIME_FUNCS:
                return True
        low = text_of(fn).lower()
        if any(t in low for t in _THROTTLE_TOKENS):
            return True
    return False


@rule("SEC006", "security", "warn", "Unthrottled automatic chat message",
      "`SendChatMessage` from an event handler or OnUpdate fires every time the trigger does. Without a "
      "rate limit it spams channels (reports, mutes, disconnects for flooding); on Mainline SAY/YELL/CHANNEL also "
      "require a hardware event.", confidence="medium", tags=("chat",))
def unthrottled_chat(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    if _is_lib(lf.rel):
        return
    assert lf.ast is not None
    onupdate = _onupdate_fns(ctx)
    for node, name in _calls(ctx, lf):
        if node.kind != "Call" or name not in ("SendChatMessage", "C_ChatInfo.SendChatMessage"):
            continue
        fn = enclosing_function(node)
        evs = _events_at(ctx, node)
        if fn is not None and id(fn) in onupdate:
            trigger = "an OnUpdate handler (every frame)"
        elif evs:
            if evs <= _ONE_SHOT_EVENTS:
                continue
            shown = sorted(evs)
            trigger = "a " + ", ".join(shown[:3]) + (", ..." if len(shown) > 3 else "") + " handler"
        else:
            continue
        if _throttled(node):
            continue
        emit(node.line, f"`{name}` is sent automatically from {trigger} with no time-based throttle.",
             fix_hint="Gate it: `local now = GetTime(); if now - lastSent < 10 then return end; lastSent = now`, "
                      "send at most once per trigger, and make automatic chat opt-in.",
             tags=[f"symbol:{name}"])


# --------------------------------------------------------------------------- SEC007


def _addon_msg_vars(fn: Node, region: Node, method_style: bool) -> tuple[Node, Node] | None:
    """Declarations of the (prefix, payload) variables in a CHAT_MSG_ADDON handler."""
    for n in region.walk():
        if n.kind == "Local" and len(n.values) == 1 and n.values[0].kind == "Vararg":
            names = list(n.names)
            if names and names[0].id.lower() in ("event", "evt", "e"):
                names = names[1:]
            if len(names) >= 2:
                return names[0], names[1]
    params = list(fn.params)
    for i, p in enumerate(params):
        if "prefix" in p.id.lower() and i + 1 < len(params):
            return p, params[i + 1]
    start = 1 if method_style else 2
    if len(params) > start and params[start].id.lower() in ("event", "evt", "e"):
        start += 1
    if len(params) >= start + 2:
        return params[start], params[start + 1]
    return None


def _prefix_checked(decl: Node) -> bool:
    for ref in decl.a.get("refs", []):
        p = ref.parent
        if p is None:
            continue
        if p.kind == "BinOp" and p.op in ("==", "~="):
            return True
        if p.kind == "Index" and p.key is ref:
            return True
        if p.kind in ("Call", "Method"):
            return True  # handed to a dispatcher / validator
        if any(a.kind == "If" and any(_contains(c, ref) for c, _ in a.clauses) for a in ref.ancestors()):
            return True
    return False


@rule("SEC007", "security", "warn", "CHAT_MSG_ADDON payload used without checking the prefix",
      "CHAT_MSG_ADDON delivers messages for every prefix this client registered, from any sender. A handler that "
      "parses the payload before matching its own prefix processes other addons' (or crafted) data.",
      scope="addon", confidence="medium", tags=("chat",))
def addon_message_prefix(ctx: AuditContext, emit: Emit) -> None:
    files = _fn_files(ctx)
    for fid, (fn, evs) in event_handler_functions(ctx).items():
        lf = files.get(fid)
        if lf is None or _is_lib(lf.rel) or "CHAT_MSG_ADDON" not in evs:
            continue
        method_style = evs == {"CHAT_MSG_ADDON"} and not any(
            h.func is fn for h in script_handlers(ctx, lf, {"OnEvent"}))
        regions: list[Node] = []
        if method_style:
            regions = [fn.body]
        else:
            for n in fn.body.walk():
                if n.kind == "If":
                    regions += [body for cond, body in n.clauses if "CHAT_MSG_ADDON" in _event_literals(cond, "==")]
            for st in fn.body.body:
                if st.kind == "If" and _exits(st.clauses[0][1]) and \
                        "CHAT_MSG_ADDON" in _event_literals(st.clauses[0][0], "~="):
                    regions.append(fn.body)
            if not regions and not any(n.kind == "If" and any(_event_literals(c, "==") | _event_literals(c, "~=")
                                                              for c, _ in n.clauses) for n in fn.body.walk()):
                regions = [fn.body]  # handler does not branch on the event at all
        for region in regions:
            found = _addon_msg_vars(fn, region, method_style)
            if found is None:
                continue
            prefix, payload = found
            if _prefix_checked(prefix):
                continue
            uses = sorted((r for r in payload.a.get("refs", []) if _contains(fn, r)), key=lambda r: r.line)
            if not uses:
                continue
            emit(uses[0].line, f"CHAT_MSG_ADDON payload `{payload.id}` is used but prefix `{prefix.id}` is never "
                               "checked: messages for every registered prefix (and from any sender) reach this code.",
                 file=lf.rel,
                 fix_hint=f"Return early on foreign traffic: `if {prefix.id} ~= MY_PREFIX then return end`, then "
                          "validate the payload (version, field count, length) before using it.")
            break


# --------------------------------------------------------------------------- SEC008

_SECRET_APIS = frozenset({
    "UnitHealth", "UnitHealthMax", "UnitPower", "UnitPowerMax", "UnitLevel", "UnitReaction", "UnitAura",
    "UnitBuff", "UnitDebuff", "UnitGetIncomingHeals", "UnitGetTotalAbsorbs", "C_UnitAuras.GetAuraDataByIndex",
    "C_UnitAuras.GetAuraDataBySlot", "C_UnitAuras.GetAuraDataByAuraInstanceID", "C_UnitAuras.GetBuffDataByIndex",
    "C_UnitAuras.GetDebuffDataByIndex",
})
_SECRET_GUARDS = ("issecretvalue", "canaccessvalue", "scrubsecretvalues", "hasanysecretvalues")


def _secret_call(e: Node | None, depth: int = 0) -> str | None:
    if e is None:
        return None
    if e.kind == "Call":
        name = dotted_name(e.func)
        if name in _SECRET_APIS:
            unit = string_arg(e, 0)
            return None if unit == "player" else name
        return None
    if e.kind == "Index" and depth < 2:
        return _secret_call(e.obj, depth + 1)  # `C_UnitAuras.GetAuraDataByIndex(u, i).spellId`
    if e.kind == "Name" and not e.a.get("is_global") and depth < 2:
        return _secret_call(_local_value(e.a.get("decl")), depth + 1)
    return None


@rule("SEC008", "security", "info", "Possibly secret value stored in SavedVariables",
      "On Midnight (12.x) and Forever, combat-sensitive unit and aura values can be secret. Secret values do not "
      "serialize (they save as nil) and touching them taints the addon. Persist them only after an "
      "`issecretvalue` check or a `tonumber`/`scrubsecretvalues` scrub.",
      confidence="low", profiles=("mainline", "forever"), tags=("secret-values",))
def secret_to_sv(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    if _is_lib(lf.rel) or not ctx.addon.saved_variables:
        return
    assert lf.ast is not None
    for node in _nodes(ctx, lf, "Assign"):
        if node.kind != "Assign":
            continue
        for i, tg in enumerate(node.targets):
            val = node.values[i] if i < len(node.values) else None
            api = _secret_call(val)
            if api is None:
                continue
            sv = _sv_target(ctx, tg)
            if sv is None or any(guarded_by(node, g) for g in _SECRET_GUARDS):
                continue
            emit(node.line, f"`{api}` result is written to SavedVariables `{sv}` without a secret-value check; for "
                            "units other than the player it can be secret in combat (saves as nil, taints the addon).",
                 fix_hint="Scrub before saving: `local v = tonumber(UnitHealth(unit))` / `scrubsecretvalues(v)`, "
                          "or skip when `issecretvalue(v)`; prefer saving outside combat.")


# --------------------------------------------------------------------------- SEC009

_ALWAYS_PROTECTED = frozenset({
    "CastSpellByName", "CastSpellByID", "CastSpell", "UseAction", "TargetUnit", "AssistUnit", "FocusUnit",
    "ClearFocus", "ClearTarget", "RunMacroText", "RunMacro", "SpellStopCasting", "TargetNearestEnemy",
    "TargetNearestFriend", "CastShapeshiftForm", "CancelShapeshiftForm", "PetAttack", "UseItemByName",
})


@rule("SEC009", "security", "error", "Call to a protected function from addon code",
      "Casting, targeting, using actions and running macros are protected: only Blizzard's secure code (e.g. a "
      "SecureActionButtonTemplate click) may call them. From addon code they always fail with "
      "ADDON_ACTION_BLOCKED/FORBIDDEN, in or out of combat.", tags=("taint",))
def protected_call(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    if _is_lib(lf.rel):
        return
    assert lf.ast is not None
    for node in _nodes(ctx, lf, "Call"):
        if node.kind != "Call":
            continue
        name = _global_ref(node.func)
        if name not in _ALWAYS_PROTECTED:
            continue
        emit(node.line, f"`{name}` is a protected function: calling it from addon Lua is blocked "
                        "(ADDON_ACTION_FORBIDDEN) regardless of combat state.", tags=[f"symbol:{name}"],
             fix_hint="Create a `SecureActionButtonTemplate` button and set attributes out of combat, e.g. "
                      "`btn:SetAttribute(\"type\", \"spell\"); btn:SetAttribute(\"spell\", name)`; the player's "
                      "click performs the action.")
