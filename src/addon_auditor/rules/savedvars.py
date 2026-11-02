"""SAVEDVARS rule pack: load order, ADDON_LOADED filtering, schema versioning, serializability, scoping and
wholesale replacement of SavedVariables tables.

Timeline (warcraft.wiki.gg "Saving variables between game sessions"): an addon's Lua files run first, then its
SavedVariables file is executed (overwriting the globals), then ADDON_LOADED fires with the addon's name.
``## LoadSavedVariablesFirst: 1`` reverses the first two steps.
"""

from __future__ import annotations

import re

from ..core.context import AuditContext
from ..core.finding import Emit, rule
from ..core.lua_ast import Node, dotted_name, enclosing_function, string_arg
from ._util import EVENT_NAME, event_handler_functions, file_scope, guarded_by
from .security import (
    _contains,
    _event_literals,
    _events_at,
    _exits,
    _fn_files,
    _global_ref,
    _is_lib,
    _local_value,
    _nodes,
    _own_files,
    _resolve_callee,
    _sv_root,
    _sv_target,
)

_INIT_EVENTS = frozenset({"ADDON_LOADED", "PLAYER_LOGIN", "VARIABLES_LOADED", "PLAYER_ENTERING_WORLD"})


def _svs(ctx: AuditContext) -> set[str]:
    return set(ctx.addon.saved_variables)


def _load_first(ctx: AuditContext) -> bool:
    return any((t.get("LoadSavedVariablesFirst") or "").strip() == "1" for t in ctx.addon.tocs)


def _sv_name(node: Node, svs: set[str]) -> bool:
    return node.kind == "Name" and bool(node.a.get("is_global")) and node.id in svs


def _is_self_or_init(name_node: Node) -> tuple[bool, bool]:
    """(is the `X = X or ...` target, is the `X` read inside that `or`)."""
    p = name_node.parent
    if p is not None and p.kind == "Assign" and name_node in p.targets:
        idx = p.targets.index(name_node)
        val = p.values[idx] if idx < len(p.values) else None
        if val is not None and val.kind == "BinOp" and val.op == "or" and val.left.kind == "Name" \
                and val.left.id == name_node.id:
            return True, False
        if val is not None and val.kind == "Table":
            return True, False  # `MyDB = {}`: a placeholder, same effect as `MyDB = MyDB or {}`
    if p is not None and p.kind == "BinOp" and p.op == "or" and p.left is name_node:
        gp = p.parent
        if gp is not None and gp.kind == "Assign" and any(t.kind == "Name" and t.id == name_node.id
                                                           for t in gp.targets):
            return False, True
    return False, False


# --------------------------------------------------------------------------- SV001


@rule("SV001", "savedvars", "warn", "SavedVariables used at file scope (before they load)",
      "WoW runs an addon's Lua files first and only then loads its SavedVariables, overwriting the globals. "
      "Anything file-scope code reads or writes on the SV table belongs to a placeholder that is thrown away.",
      scope="addon")
def file_scope_use(ctx: AuditContext, emit: Emit) -> None:
    svs = _svs(ctx)
    if not svs or _load_first(ctx):
        return
    fn_init: set[str] = set()
    for lf in _own_files(ctx):
        assert lf.ast is not None
        for node in _nodes(ctx, lf, "Name"):
            if _sv_name(node, svs) and node.a.get("is_write") and not file_scope(node):
                fn_init.add(node.id)
    any_use: set[str] = set()
    pending_init: list[tuple[str, Node, str]] = []
    for lf in _own_files(ctx):
        assert lf.ast is not None
        uses: dict[str, Node] = {}
        inits: dict[str, Node] = {}
        for node in _nodes(ctx, lf, "Name"):
            if not _sv_name(node, svs) or not file_scope(node):
                continue
            is_init, is_init_read = _is_self_or_init(node)
            if is_init_read:
                continue
            bucket = inits if is_init else uses
            if node.id not in bucket or node.line < bucket[node.id].line:
                bucket[node.id] = node
        for sv, node in sorted(uses.items()):
            any_use.add(sv)
            emit(node.line, _use_message(node, sv), file=lf.rel, tags=[f"symbol:{sv}"],
                 fix_hint=f"Move this into an ADDON_LOADED handler (`if addonName == ... then {sv} = {sv} or {{}}; "
                          "<defaults/migration>; ns.db = " + sv + " end`) or PLAYER_LOGIN; at file scope only define "
                          "functions and defaults tables.")
        pending_init += [(sv, node, lf.rel) for sv, node in inits.items()]
    for sv, node, rel in sorted(pending_init, key=lambda x: (x[2], x[1].line)):
        if sv in fn_init or sv in any_use:
            continue
        emit(node.line, f"File-scope `{sv} = ...` runs before SavedVariables load: `{sv}` is always nil here, and "
                        "the table built now is replaced by the saved one (defaults in it are lost once a saved "
                        "file exists); no real initialisation happens here.", file=rel, severity="info", confidence="medium", tags=[f"symbol:{sv}"],
             fix_hint=f"Initialise `{sv}` (defaults, migration) in ADDON_LOADED for this addon or PLAYER_LOGIN, or "
                      "declare `## LoadSavedVariablesFirst: 1` in the TOC if the client supports it.")


def _use_message(node: Node, sv: str) -> str:
    p = node.parent
    base = f"`{sv}` is used at file scope, before WoW loads SavedVariables"
    if p is not None and p.kind == "Local":
        return (f"{base}: this local keeps the pre-load value (nil or a placeholder table); after load `{sv}` points "
                "to the saved table and the local is stale, so settings appear to reset every session.")
    if p is not None and p.kind == "Index" and p.obj is node:
        gp = p.parent
        if gp is not None and gp.kind == "Assign" and any(_contains(t, p) for t in gp.targets):
            return (f"{base}: fields written here go into a placeholder table that the saved `{sv}` replaces "
                    "(defaults are lost when a saved file exists).")
        return f"{base}: reads here see nil/placeholder data, never the saved values."
    if p is not None and p.kind == "Assign" and node in p.targets:
        return f"{base}: this assignment is overwritten as soon as the SavedVariables file loads."
    if p is not None and p.kind in ("Call", "Method"):
        return f"{base}: the call receives the placeholder, not the saved table (migrations/defaults are lost)."
    return f"{base}: it is nil or a placeholder here, not the saved data."


# --------------------------------------------------------------------------- SV002


def _vararg_name_decls(ctx: AuditContext) -> set[int]:
    """Declarations of ``local addonName, ns = ...`` (main chunk) and ``local ADDON = "<name>"`` constants."""
    out: set[int] = set()
    for lf in _own_files(ctx):
        assert lf.ast is not None
        for st in lf.ast.body.body:
            if st.kind != "Local":
                continue
            if len(st.values) == 1 and st.values[0].kind == "Vararg" and st.names:
                out.add(id(st.names[0]))
            for i, nm in enumerate(st.names):
                if i < len(st.values) and st.values[i].kind == "String" \
                        and str(st.values[i].value).lower() == ctx.addon.name.lower():
                    out.add(id(nm))
    return out


_ADDON_NAME_LIT = re.compile(r"^[A-Za-z][\w.-]*$")


def _is_own_name_expr(ctx: AuditContext, e: Node, name_decls: set[int], other: Node | None = None) -> bool:
    if e.kind == "String":
        s = str(e.value)
        if s.lower() == ctx.addon.name.lower():
            return True
        # Another addon's name (`arg1 == "Blizzard_AuctionHouseUI"`) also means the handler filters.
        return (other is not None and other.kind == "Name" and not EVENT_NAME.match(s)
                and bool(_ADDON_NAME_LIT.match(s)) and ("_" in s or s[:1].isupper()))
    if e.kind == "Name":
        decl = e.a.get("decl")
        if decl is not None and id(decl) in name_decls:
            return True
        low = e.id.lower()
        return "addon" in low and "name" in low
    dn = dotted_name(e)
    if dn:
        low = dn.lower()
        return ("addon" in low and "name" in low) or low.endswith((".name", ".addonname", ".addon_name"))
    return False


def _checks_own_name(ctx: AuditContext, fn: Node, name_decls: set[int]) -> bool:
    for n in fn.walk():
        if n.kind == "BinOp" and n.op in ("==", "~="):
            if (_is_own_name_expr(ctx, n.left, name_decls, n.right)
                    or _is_own_name_expr(ctx, n.right, name_decls, n.left)):
                return True
    return False


def _first_sv_ref(ctx: AuditContext, region: Node, svs: set[str], depth: int = 0) -> Node | None:
    """First SV reference in ``region`` or (one level) in functions it calls."""
    best: Node | None = None
    files = _fn_files(ctx)
    for n in region.walk():
        if _sv_name(n, svs):
            if best is None or n.line < best.line:
                best = n
    if best is not None or depth > 0:
        return best
    fn = enclosing_function(region) if region.kind != "Function" else region
    lf = files.get(id(fn)) if fn is not None else None
    if lf is None:
        return None
    for n in region.walk():
        if n.kind in ("Call", "Method"):
            callee = _resolve_callee(ctx, lf, n)
            if callee is not None and callee is not fn and _first_sv_ref(ctx, callee.body, svs, depth + 1):
                return n
    return None


@rule("SV002", "savedvars", "warn", "ADDON_LOADED handler does not check the addon name",
      "ADDON_LOADED fires once for every addon (and every load-on-demand Blizzard module). Initialising "
      "SavedVariables without checking the name argument runs the init too early (before this addon's SVs are "
      "loaded) and again for every later addon, resetting or re-merging data.", scope="addon", confidence="medium")
def addon_loaded_unfiltered(ctx: AuditContext, emit: Emit) -> None:
    svs = _svs(ctx)
    if not svs:
        return
    files = _fn_files(ctx)
    name_decls = _vararg_name_decls(ctx)
    for fid, (fn, evs) in event_handler_functions(ctx).items():
        lf = files.get(fid)
        if lf is None or _is_lib(lf.rel) or "ADDON_LOADED" not in evs:
            continue
        regions: list[Node] = []
        if evs == {"ADDON_LOADED"}:
            regions = [fn.body]
        else:
            for n in fn.body.walk():
                if n.kind == "If":
                    regions += [b for c, b in n.clauses if "ADDON_LOADED" in _event_literals(c, "==")]
            for st in fn.body.body:
                if st.kind == "If" and _exits(st.clauses[0][1]) and \
                        "ADDON_LOADED" in _event_literals(st.clauses[0][0], "~="):
                    regions.append(fn.body)
        if not regions or _checks_own_name(ctx, fn, name_decls):
            continue
        for region in regions:
            ref = _first_sv_ref(ctx, region, svs)
            if ref is None:
                continue
            emit(ref.line, "SavedVariables are initialised in an ADDON_LOADED handler that never compares the "
                           "loaded addon's name, so this runs for every addon that loads (the first time before "
                           "this addon's SavedVariables exist).", file=lf.rel,
                 fix_hint="Filter first: `local addonName = ...` at file top, then in the handler "
                          "`if loadedName ~= addonName then return end` and "
                          "`self:UnregisterEvent(\"ADDON_LOADED\")` after initialising.")
            break


# --------------------------------------------------------------------------- SV003

_VERSION_KEY = re.compile(r"version|schema|revision|dbver|db_ver", re.I)
_DEFAULTS_NAME = re.compile(r"defaults$|^default_?(?:settings|config|options|db|saved(?:_?table)?|profile|vars)?$|"
                            r"^(?:db|sv|saved)_?defaults?$", re.I)


def _table_keys(t: Node, out: set[str], depth: int = 0) -> None:
    for f in t.fields:
        if f.kind == "Field" and f.key.kind == "String":
            out.add(str(f.key.value))
        if f.value.kind == "Table" and depth < 4:
            _table_keys(f.value, out, depth + 1)


@rule("SV003", "savedvars", "info", "SavedVariables defaults without a schema version",
      "Once settings are nested, renaming or restructuring a key needs a migration. Without a version field in the "
      "saved table there is no reliable way to tell old data from new.", scope="addon", confidence="low")
def no_schema_version(ctx: AuditContext, emit: Emit) -> None:
    svs = _svs(ctx)
    if not svs:
        return
    keys: set[str] = set()
    anchor: tuple[str, int] | None = None
    fallback: tuple[str, int] | None = None
    for lf in _own_files(ctx):
        assert lf.ast is not None
        if "AceDB-3.0" in lf.src:
            return  # AceDB manages defaults/profiles
        for node in _nodes(ctx, lf, "Index", "Assign", "Local"):
            if node.kind == "Index" and node.key.kind == "String" and _VERSION_KEY.search(str(node.key.value)) \
                    and _sv_root(ctx, node.obj) is not None:
                return  # MyDB.schemaVersion / ns.db.version
            if node.kind not in ("Assign", "Local"):
                continue
            targets = node.targets if node.kind == "Assign" else node.names
            for i, tg in enumerate(targets):
                val = node.values[i] if i < len(node.values) else None
                if val is not None and val.kind == "BinOp" and val.op == "or":
                    val = val.right
                is_defaults = bool(_DEFAULTS_NAME.search((dotted_name(tg) or "").rsplit(".", 1)[-1]))
                is_sv = node.kind == "Assign" and _sv_target(ctx, tg) is not None
                if not (is_defaults or is_sv):
                    continue
                if val is not None and val.kind == "Table":
                    before = len(keys)
                    _table_keys(val, keys)
                    if len(keys) > before and anchor is None:
                        anchor = (lf.rel, node.line)
                elif is_sv and tg.kind == "Index" and tg.key.kind == "String":
                    keys.add(str(tg.key.value))
                    if fallback is None:
                        fallback = (lf.rel, node.line)
    anchor = anchor or fallback
    if anchor is None or len(keys) < 6 or any(_VERSION_KEY.search(k) for k in keys):
        return
    sv = sorted(svs)[0]
    emit(anchor[1], f"{len(keys)} default/SavedVariables keys but no version or schema field: future changes to "
                    "this layout cannot be migrated reliably.", file=anchor[0],
         fix_hint=f"Add `schemaVersion = 1` to the defaults and a migrate step on load: "
                  f"`if ({sv}.schemaVersion or 0) < 2 then ... end; {sv}.schemaVersion = 2`.")


# --------------------------------------------------------------------------- SV004

_REGION_CREATORS = frozenset({"CreateTexture", "CreateFontString", "CreateAnimationGroup", "CreateMaskTexture",
                              "CreateLine", "CreateAnimation"})


def _unserializable(e: Node | None, depth: int = 0) -> str | None:
    if e is None or depth > 3:
        return None
    if e.kind == "Function":
        return "a function"
    if e.kind == "Call" and _global_ref(e.func) == "CreateFrame":
        return "a frame"
    if e.kind == "Method" and e.name in _REGION_CREATORS:
        return "a UI region"
    if e.kind == "Call" and dotted_name(e.func) == "coroutine.create":
        return "a coroutine"
    if e.kind == "Name" and not e.a.get("is_global"):
        decl = e.a.get("decl")
        if decl is not None and decl.parent is not None and decl.parent.kind == "LocalFunction":
            return "a function"
        return _unserializable(_local_value(decl), depth + 1)
    if e.kind == "Table":
        for f in e.fields:
            found = _unserializable(f.value, depth + 1)
            if found:
                return found
    return None


@rule("SV004", "savedvars", "error", "Function or frame stored in SavedVariables",
      "SavedVariables only serialize nil, booleans, numbers, strings and tables of those. Functions, frames and "
      "other userdata are silently dropped (or break the save), so the data is gone next session.", scope="addon")
def unserializable_value(ctx: AuditContext, emit: Emit) -> None:
    if not _svs(ctx):
        return
    for lf in _own_files(ctx):
        assert lf.ast is not None
        for node in _nodes(ctx, lf, "Assign", "FunctionDecl", "Call"):
            pairs: list[tuple[Node, Node | None]] = []
            if node.kind == "Assign":
                pairs = [(tg, node.values[i] if i < len(node.values) else None) for i, tg in enumerate(node.targets)]
            elif node.kind == "FunctionDecl":
                pairs = [(node.target, node.func)]
            elif node.kind == "Call" and dotted_name(node.func) in ("tinsert", "table.insert") and len(node.args) >= 2:
                sv = _sv_root(ctx, node.args[0])
                what = _unserializable(node.args[-1])
                if sv and what:
                    _emit_unser(emit, lf.rel, node.line, sv, what)
                continue
            for tg, val in pairs:
                what = _unserializable(val)
                if what is None:
                    continue
                sv = _sv_target(ctx, tg)
                if sv is None:
                    continue
                _emit_unser(emit, lf.rel, node.line, sv, what)


def _emit_unser(emit: Emit, rel: str, line: int, sv: str, what: str) -> None:
    emit(line, f"Stores {what} in SavedVariables `{sv}`: it cannot be serialized and is lost (or corrupts the "
               "save) on logout.", file=rel, tags=[f"symbol:{sv}"],
         fix_hint="Save plain data instead (a frame's name via `frame:GetName()`, a position table, an id/key "
                  "that selects the function) and keep functions/frames in a non-saved Lua table.")


# --------------------------------------------------------------------------- SV005

_CHAR_APIS = frozenset({"UnitName", "GetRealmName", "UnitGUID", "GetNormalizedRealmName", "UnitFullName"})


def _char_keyed(e: Node, depth: int = 0) -> bool:
    for n in e.walk():
        if n.kind == "Call" and dotted_name(n.func) in _CHAR_APIS:
            if dotted_name(n.func) in ("GetRealmName", "GetNormalizedRealmName") or string_arg(n, 0) == "player":
                return True
        if n.kind == "Name" and not n.a.get("is_global") and depth < 2:
            val = _local_value(n.a.get("decl"))
            if val is not None and _char_keyed(val, depth + 1):
                return True
    return False


@rule("SV005", "savedvars", "info", "Per-character SavedVariables keyed by character",
      "SavedVariablesPerCharacter is already stored per character. Keying it by player name/realm duplicates that "
      "scoping and suggests the data was meant to be account-wide (e.g. an alt overview).", scope="addon",
      confidence="low")
def per_char_keyed(ctx: AuditContext, emit: Emit) -> None:
    per_char: set[str] = set()
    account: set[str] = set()
    for t in ctx.addon.tocs:
        per_char |= set(t.saved_variables_per_character)
        account |= set(t.saved_variables)
    per_char -= account
    if not per_char:
        return
    seen: set[str] = set()
    for lf in _own_files(ctx):
        assert lf.ast is not None
        for node in _nodes(ctx, lf, "Index"):
            if node.kind != "Index" or node.key.kind == "String":
                continue
            sv = _sv_root(ctx, node.obj)
            if sv not in per_char or sv in seen or not _char_keyed(node.key):
                continue
            seen.add(sv)
            emit(node.line, f"`{sv}` is a per-character SavedVariable but is indexed by the character's "
                            "name/realm: each character's file only ever holds its own entry.", file=lf.rel,
                 fix_hint=f"Drop the character key and store the fields on `{sv}` directly, or move the table to "
                          "`## SavedVariables` (account-wide) if other characters should see it.")


# --------------------------------------------------------------------------- SV006

_RESET_WORDS = re.compile(r"reset|wipe|clear|purge|default|init|load|migrat|upgrade|onaccept|restore|import",
                          re.I)


def _fn_label(fn: Node) -> str:
    label = fn.a.get("fname") or ""
    p = fn.parent
    if p is not None:
        if p.kind == "Local":
            label += " " + " ".join(n.id for n in p.names)
        elif p.kind == "Assign":
            label += " " + " ".join(dotted_name(t) or "" for t in p.targets)
        elif p.kind == "Field" and p.key.kind == "String":
            label += " " + str(p.key.value)
    return label


def _intentional_reset(node: Node) -> bool:
    for anc in node.ancestors():
        if anc.kind == "If":
            for cond, _body in anc.clauses:
                if any(n.kind == "String" and _RESET_WORDS.search(str(n.value)) for n in cond.walk()):
                    return True
                if any(n.kind == "Name" and _RESET_WORDS.search(n.id) for n in cond.walk()):
                    return True
        if anc.kind == "Function" and _RESET_WORDS.search(_fn_label(anc)):
            return True
    return False


@rule("SV006", "savedvars", "warn", "SavedVariables table replaced after load",
      "Assigning a fresh table to a SavedVariable at runtime discards everything the player saved. Outside an "
      "explicit reset this is usually a misplaced initialisation.", scope="addon", confidence="medium")
def sv_replaced(ctx: AuditContext, emit: Emit) -> None:
    svs = _svs(ctx)
    if not svs:
        return
    for lf in _own_files(ctx):
        assert lf.ast is not None
        for node in _nodes(ctx, lf, "Assign"):
            if node.kind != "Assign" or file_scope(node):
                continue
            for i, tg in enumerate(node.targets):
                if not _sv_name(tg, svs) or i >= len(node.values):
                    continue
                val = node.values[i]
                fresh = val.kind == "Table" or (
                    val.kind == "Call" and "copy" in (dotted_name(val.func) or "").lower())
                if not fresh or guarded_by(node, tg.id) or _intentional_reset(node):
                    continue
                evs = _events_at(ctx, node)
                if evs and evs & _INIT_EVENTS:
                    continue
                emit(node.line, f"`{tg.id}` is replaced with a new table at runtime: all saved data in it is "
                                "discarded.", file=lf.rel, tags=[f"symbol:{tg.id}"],
                     fix_hint=f"Fill missing keys instead (`{tg.id} = {tg.id} or {{}}` plus per-key defaults), or "
                              "make it an explicit, confirmed reset (slash `reset` / StaticPopup OnAccept) that "
                              "keeps what must survive.")
