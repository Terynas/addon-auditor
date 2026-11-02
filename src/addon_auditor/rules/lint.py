"""LINT: luacheck findings plus syntax errors from the built-in parser."""

from __future__ import annotations

import re

from ..adapters import luacheck
from ..core.context import AuditContext
from ..core.finding import Emit, rule
from ._util import existence_checked, find_names_at

_SYMBOL = re.compile(r"'([^']+)'")


def allowed_globals(ctx: AuditContext) -> list[str]:
    """Globals the addon may legitimately write: SavedVariables, slash/binding names, addon-prefixed names."""
    allowed: list[str] = list(ctx.addon.saved_variables) + list(ctx.config.extra_globals)
    lname = ctx.addon.name.lower()
    for name in ctx.addon_globals:
        if name.startswith("SLASH_") or name.lower().startswith(lname) or name.startswith("BINDING_"):
            allowed.append(name)
    allowed += [n for n in ctx.xml_global_names if n.lower().startswith(lname)]
    return sorted(set(allowed))


def used_client_globals(ctx: AuditContext) -> list[str]:
    """Client globals the addon reads that exist in at least one targeted client."""
    from ..core.builtins import ALWAYS_KNOWN

    used: set[str] = set()
    for lf in ctx.parsed_files():
        assert lf.ast is not None
        for node in lf.ast.walk():
            if node.kind == "Name" and node.a.get("is_global") and not node.a.get("is_write"):
                used.add(node.id)
    own = set(ctx.addon_globals)
    return sorted(n for n in used - own if n not in ALWAYS_KNOWN and any(ctx.api.global_in(n).values()))


def _luacheck_result(ctx: AuditContext) -> luacheck.LuacheckResult:
    cached = getattr(ctx, "_luacheck", None)
    if cached is not None:
        return cached
    files = [lf.rel for lf in ctx.lua_files()]
    res = luacheck.run(ctx.root, files, set(ctx.profiles), allowed_globals(ctx))
    ctx._luacheck = res  # type: ignore[attr-defined]
    if not res.available:
        notes = getattr(ctx, "notes", [])
        notes.append(f"luacheck skipped: {res.error}")
        ctx.notes = notes  # type: ignore[attr-defined]
    elif res.error:
        notes = getattr(ctx, "notes", [])
        notes.append(f"luacheck error: {res.error[:300]}")
        ctx.notes = notes  # type: ignore[attr-defined]
    return res


def _emit_codes(ctx: AuditContext, emit: Emit, pred, fix=None) -> None:  # type: ignore[no-untyped-def]
    if not getattr(ctx, "run_luacheck", True):
        return
    res = _luacheck_result(ctx)
    for issue in res.issues:
        if not pred(issue.code):
            continue
        tags = []
        m = _SYMBOL.search(issue.message)
        if m and issue.code in ("W111", "W112", "W113", "W121", "W122"):
            tags.append(f"symbol:{m.group(1)}")
        emit(issue.line, f"{issue.message} [luacheck {issue.code}]", file=issue.file, col=issue.col,
             fix_hint=fix(issue) if fix else None, tags=tags)


@rule("LINT001", "lint", "error", "Lua syntax error",
      "The file does not parse as Lua 5.1, so WoW will refuse to load it (and everything after it in the TOC).",
      scope="addon")
def syntax_error(ctx: AuditContext, emit: Emit) -> None:
    lc_files = set()
    if getattr(ctx, "run_luacheck", True):
        res = _luacheck_result(ctx)
        for issue in res.issues:
            if issue.code.startswith("E"):
                lc_files.add(issue.file)
                emit(issue.line, f"{issue.message} [luacheck {issue.code}]", file=issue.file, col=issue.col)
    for lf in ctx.lua_files():
        if lf.parse_error is not None and lf.rel not in lc_files:
            emit(lf.parse_error.line, str(lf.parse_error), file=lf.rel, col=lf.parse_error.col)


@rule("LINT002", "lint", "warn", "Access to an undefined global",
      "Reading a global that neither the addon nor the client defines: usually a typo, a missing `local`, "
      "or an API that does not exist on this client.", scope="addon", tags=("api-correctness",))
def undefined_global(ctx: AuditContext, emit: Emit) -> None:
    if not getattr(ctx, "run_luacheck", True):
        return
    res = _luacheck_result(ctx)
    deps = [d.lower() for t in ctx.addon.tocs for d in t.dependencies + t.optional_deps]
    uncovered = ctx.api.uncovered
    for issue in res.issues:
        if issue.code != "W113":
            continue
        m = _SYMBOL.search(issue.message)
        sym = m.group(1) if m else ""
        lf = ctx.files.get(issue.file)
        if lf is not None and sym and any(existence_checked(n, sym) for n in find_names_at(lf, issue.line, sym)):
            continue  # defensive access; API rules judge per-client availability
        if sym and any(sym.lower().startswith(d.split("-")[0]) for d in deps if d):
            continue  # global exported by a declared dependency
        msg = f"{issue.message} [luacheck W113]"
        sev = None
        conf = None
        if uncovered:
            msg += f" (no bundled API data for {', '.join(uncovered)}; may exist there)"
            sev, conf = "info", "low"
        emit(issue.line, msg, file=issue.file, col=issue.col, severity=sev, confidence=conf,  # type: ignore[arg-type]
             tags=[f"symbol:{sym}"] if sym else [],
             fix_hint="Check spelling / declare it `local`, or verify the API exists for this client "
                      "(`addon-auditor api <Name>`); guard optional APIs with `if X then`.")


@rule("LINT003", "lint", "warn", "Accidental global variable",
      "Assigning a global the addon did not intend to export. Globals leak into the shared environment, "
      "collide with other addons and are slower than locals.", scope="addon", tags=("performance",))
def accidental_global(ctx: AuditContext, emit: Emit) -> None:
    _emit_codes(ctx, emit, lambda c: c in ("W111", "W112"),
                lambda i: "Add `local` to the declaration, or keep exported state on one prefixed namespace "
                          "table (e.g. `MyAddon = MyAddon or {}`).")


@rule("LINT004", "lint", "error", "Overwriting a read-only (Blizzard) global",
      "Assigning to a client-defined global (API function, FrameXML function, frame) replaces it for every "
      "addon and the default UI, and taints secure code paths.", scope="addon", tags=("taint",))
def readonly_global(ctx: AuditContext, emit: Emit) -> None:
    _emit_codes(ctx, emit, lambda c: c in ("W121", "W122"),
                lambda i: "Use `hooksecurefunc(\"Name\", fn)` to run after it, or a local copy; never replace it.")


@rule("LINT005", "lint", "info", "Unused variable / value",
      "Unused locals, arguments or assigned values: dead code or a logic slip.", scope="addon")
def unused(ctx: AuditContext, emit: Emit) -> None:
    _emit_codes(ctx, emit, lambda c: c[1] in "23")


@rule("LINT006", "lint", "info", "Shadowed variable",
      "A local shadows an outer local or upvalue; easy source of 'it works in one place' bugs.", scope="addon")
def shadowing(ctx: AuditContext, emit: Emit) -> None:
    _emit_codes(ctx, emit, lambda c: c[1] == "4")


@rule("LINT007", "lint", "warn", "Suspicious control flow",
      "Unreachable code, loops that run once, empty branches.", scope="addon")
def control_flow(ctx: AuditContext, emit: Emit) -> None:
    _emit_codes(ctx, emit, lambda c: c[1] == "5")


@rule("LINT008", "lint", "info", "Style / formatting",
      "Whitespace and line-length issues reported by luacheck.", scope="addon")
def style(ctx: AuditContext, emit: Emit) -> None:
    _emit_codes(ctx, emit, lambda c: c[1] == "6")


_GLOBAL_OFF = re.compile(r"^\s*(?:global\s*=\s*false|allow_defined(?:_top)?\s*=\s*true)", re.M)
_IGNORE_GLOBALS = re.compile(r"ignore\s*=\s*\{[^}]*[\"'](?:1|11|1\d\d|11\d|111|112|113)[\"']", re.S)


@rule("LINT009", "lint", "warn", ".luacheckrc disables global checks",
      "Turning off global warnings (global=false, allow_defined, ignoring 11x) hides the most valuable "
      "luacheck signal: accidental globals and invented APIs.", scope="addon")
def luacheckrc_globals_off(ctx: AuditContext, emit: Emit) -> None:
    cfg = luacheck.find_config(ctx.root)
    if cfg is None:
        return
    try:
        rel = cfg.relative_to(ctx.root).as_posix()
    except ValueError:
        return  # parent workspace config: not this addon's to fix
    text = cfg.read_text(encoding="utf-8", errors="replace")
    for regex in (_GLOBAL_OFF, _IGNORE_GLOBALS):
        m = regex.search(text)
        if m:
            line = text.count("\n", 0, m.start()) + 1
            emit(line, "Global-variable warnings are disabled; list intended globals in `globals = {...}` instead.",
                 file=rel)
