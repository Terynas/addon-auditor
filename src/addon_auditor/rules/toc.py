"""TOC rule pack: the manifest decides whether (and what) the client loads."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from ..core.context import AuditContext
from ..core.finding import Emit, rule
from ..core.lua_ast import Node
from ..core.toc import TOC_SUFFIXES, Toc
from .packaging import load_pkgmeta, pkg_ignored, under_external

# Suffix -> accepted Interface ranges [lo, hi). Mainline is a family that also covers Forever (16xxx).
_RETAIL = (100000, 140000)
_SUFFIX_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "standard": (_RETAIL,), "mainline": (_RETAIL, (16000, 20000)),
    "plunderstorm": (_RETAIL,), "wowlabs": (_RETAIL,), "wowhack": (_RETAIL,),
    "forever": ((16000, 20000),), "camelot": ((16000, 20000),),
    "vanilla": ((10000, 20000),), "classic": ((10000, 60000),),
    "tbc": ((20000, 30000),), "bcc": ((20000, 30000),),
    "wrath": ((30000, 40000),), "wotlkc": ((30000, 40000),),
    "cata": ((40000, 50000),), "mists": ((50000, 60000),),
}
KNOWN_SUFFIXES = set(TOC_SUFFIXES) | set(_SUFFIX_RANGES)

_FAMILIES = {
    "mainline": {"standard", "forever", "camelot", "plunderstorm", "wowlabs", "wowhack"},
    "classic": {"vanilla", "tbc", "wrath", "cata", "mists"},
}
GAME_TYPES = {"mainline", "standard", "classic", "vanilla", "tbc", "wrath", "cata", "mists", "forever", "camelot",
              "plunderstorm", "wowlabs", "wowhack"}
_INLINE_GT = re.compile(r"\[(Allow|Exclude)LoadGameType\s+([^\]]*)\]", re.I)


def _toc_file(toc: Toc) -> str:
    return toc.path.name


def _split_suffix(stem: str, addon: str) -> str | None:
    """Return the suffix of ``<addon>_<Suffix>`` / ``<addon>-<Suffix>``; '' for an exact match; None otherwise."""
    if stem == addon:
        return ""
    for sep in ("_", "-"):
        if stem.startswith(addon + sep):
            return stem[len(addon) + 1:]
    return None


def _strip_cond(value: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", value).strip()


_UP = re.compile(r"(^|[\\/])\.\.[\\/]")
_XML_FILE_ATTR = re.compile(r"\bfile\s*=\s*\"([^\"]+)\"", re.I)


def _raw_entry(owner: object, line: int) -> str | None:
    """Path exactly as written at ``line`` of a TOC or XML file (the context normalises ``..`` away)."""
    if isinstance(owner, Toc):
        return next((e.path for e in owner.files if e.line == line), None)
    lines = owner.text.splitlines()  # type: ignore[attr-defined]
    m = _XML_FILE_ATTR.search(lines[line - 1]) if 0 < line <= len(lines) else None
    return m.group(1) if m else None


def _loads_outside_root(ctx: AuditContext) -> bool:
    """Some TOC/XML entry reaches into another addon folder (``..\\Other\\file.xml``)."""
    if any(_UP.search(e.path) for t in ctx.addon.tocs for e in t.files):
        return True
    return any(_UP.search(m.group(1)) for xf in ctx.xml_files.values() for m in _XML_FILE_ATTR.finditer(xf.text))


def _referenced_by_siblings(ctx: AuditContext) -> bool:
    """Another addon next to this one loads files from it (``..\\ThisAddon\\...`` in its TOC/XML)."""
    cached = getattr(ctx, "_toc_sibling_ref", None)
    if cached is not None:
        return bool(cached)
    pat = re.compile(r"\.\.[\\/](?:\.\.[\\/])?" + re.escape(ctx.addon.name) + r"[\\/]", re.I)
    found = False
    budget = 4000
    parent = ctx.root.parent
    try:
        siblings = [d for d in parent.iterdir() if d.is_dir() and d != ctx.root and any(d.glob("*.toc"))]
    except OSError:
        siblings = []
    for d in siblings:
        cands = list(d.glob("*.toc")) + [p for depth in ("*.xml", "*/*.xml", "*/*/*.xml") for p in d.glob(depth)]
        for p in cands:
            budget -= 1
            if budget < 0:
                break
            try:
                if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                    found = True
                    break
            except OSError:
                continue
        if found or budget < 0:
            break
    ctx._toc_sibling_ref = found  # type: ignore[attr-defined]
    return found


# --------------------------------------------------------------------------- naming / interface


@rule("TOC001", "toc", "error", "TOC file name does not match the addon folder",
      "WoW only reads `<Folder>.toc` or `<Folder>_<Suffix>.toc` with a known client suffix. Any other TOC name is "
      "ignored, and if no TOC matches, the addon does not appear in the AddOns list at all.", scope="addon")
def toc_name(ctx: AuditContext, emit: Emit) -> None:
    name = ctx.addon.name
    paths = sorted(ctx.root.glob("*.toc"))
    valid = []
    bad: list[tuple[Path, str]] = []
    for p in paths:
        suffix = _split_suffix(p.stem, name)
        if suffix == "" or (suffix and suffix.lower() in KNOWN_SUFFIXES):
            valid.append(p)
        elif suffix is not None:
            bad.append((p, f"suffix '{suffix}' is not a client suffix ({', '.join(sorted(KNOWN_SUFFIXES))})"))
        else:
            bad.append((p, f"it does not start with the folder name '{name}'"))
    if bad and not valid:
        emit(None, f"No TOC matches the folder name '{name}', so WoW will not list the addon "
             f"(found: {', '.join(p.name for p, _ in bad)}).", file=bad[0][0].name,
             fix_hint=f"Rename the folder or the TOC so they match exactly (including case): {name}/{name}.toc.")
        return
    for p, why in bad:
        emit(None, f"{p.name} is never read by the client: {why}.", file=p.name, severity="warn",
             fix_hint=f"Rename it to {name}.toc or {name}_<Mainline|Vanilla|Mists|...>.toc, or delete it.")


@rule("TOC002", "toc", "error", "Missing or invalid ## Interface",
      "Without a valid `## Interface` number the addon is flagged out of date on every client (or not loaded).",
      scope="addon")
def interface_valid(ctx: AuditContext, emit: Emit) -> None:
    for toc in ctx.addon.tocs:
        keys = [k for k in toc.directives if k.lower() == "interface" or k.lower().startswith("interface-")]
        if not keys:
            emit(1, f"{_toc_file(toc)} has no '## Interface:' line.", file=_toc_file(toc),
                 fix_hint="Add e.g. `## Interface: 16001, 120107` (comma-separate one number per client).")
            continue
        for key in keys:
            raw = _strip_cond(toc.directives[key])
            line = toc.directive_lines[key]
            parts = [p for p in re.split(r"[,\s]+", raw) if p]
            if not parts:
                emit(line, f"'## {key}:' is empty.", file=_toc_file(toc),
                     fix_hint="Use the client's interface number, e.g. 120107 (Midnight) or 16001 (Forever).")
                continue
            for part in parts:
                if not part.isdigit():
                    emit(line, f"Interface value '{part}' is not a number.", file=_toc_file(toc),
                         fix_hint="Interface numbers are plain integers (12.1.7 -> 120107, 1.60.1 -> 16001).")
                elif int(part) != 0 and not 10000 <= int(part) < 140000:  # 0 = deliberate "unsupported" TOC
                    emit(line, f"Interface value {part} is outside any known client range (10000-139999).",
                         file=_toc_file(toc),
                         fix_hint="Check `/dump select(4, GetBuildInfo())` in-game for the right number.")


@rule("TOC003", "toc", "error", "Per-client TOC suffix does not match its Interface",
      "A `_Vanilla.toc` is only read by Classic Era, a `_Mainline.toc` only by the Mainline family, etc. If none "
      "of its Interface numbers belong to that client, the addon shows as out of date there.", scope="addon")
def suffix_interface(ctx: AuditContext, emit: Emit) -> None:
    for toc in ctx.addon.tocs:
        if not toc.suffix:
            continue
        ranges = _SUFFIX_RANGES.get(toc.suffix.lower())
        ifaces = toc.interfaces
        if not ranges or not ifaces:
            continue
        if any(lo <= i < hi for i in ifaces for lo, hi in ranges):
            continue
        want = " or ".join(f"{lo}-{hi - 1}" for lo, hi in ranges)
        emit(toc.line_of("Interface"), f"{_toc_file(toc)} is the {toc.suffix} TOC but its Interface "
             f"({', '.join(map(str, ifaces))}) is not a {toc.suffix} build (expected {want}).",
             file=_toc_file(toc), fix_hint="Use the interface number of the client this suffix targets, or rename "
                                         "the TOC to the matching suffix.")


# --------------------------------------------------------------------------- file list


def _owner_file(owner: object) -> str:
    return owner.path.name if isinstance(owner, Toc) else owner.rel  # type: ignore[attr-defined]


@rule("TOC004", "toc", "error", "TOC / XML lists a file that does not exist",
      "The client logs 'file not found' and skips the entry; anything defined there is nil for the rest of the "
      "addon, so the first call into it errors.", scope="addon")
def missing_file(ctx: AuditContext, emit: Emit) -> None:
    pm = load_pkgmeta(ctx.root)
    for owner, rel, line in ctx.missing_files:
        if under_external(pm, rel):
            continue  # fetched by the packager from .pkgmeta externals
        raw = _raw_entry(owner, line) or rel
        if _UP.search(raw):
            # Reaches into a sibling addon (Bagnon -> ..\BagBrother\...): resolve against the real filesystem.
            base = ctx.root if isinstance(owner, Toc) else (ctx.root / owner.rel).parent  # type: ignore[attr-defined]
            target = (base / raw.replace("\\", "/")).resolve()
            if target.exists():
                continue
            emit(line, f"'{raw}' points outside the addon folder and was not found next to it.",
                 file=_owner_file(owner), severity="warn", confidence="low",
                 fix_hint="Make sure the addon it points into is installed/shipped together with this one.")
            continue
        emit(line, f"'{rel}' is listed but does not exist.", file=_owner_file(owner),
             fix_hint="Fix the path (it is relative to the addon folder / the XML file) or remove the entry.")


@rule("TOC005", "toc", "warn", "File path case differs from the file on disk",
      "Windows ignores case, but Linux (Wine/Proton), case-sensitive macOS volumes and some packagers do not, so "
      "the file silently fails to load there.", scope="addon")
def case_mismatch(ctx: AuditContext, emit: Emit) -> None:
    for owner, written, actual, line in ctx.case_mismatch:
        emit(line, f"'{written}' is '{actual}' on disk.", file=_owner_file(owner),
             fix_hint=f"Write the path exactly as on disk: {actual}")


def _variable_patterns(ctx: AuditContext) -> list[str]:
    pats = []
    for toc in ctx.addon.tocs:
        for e in toc.files:
            if "[" in e.path:
                pats.append(re.sub(r"\[[^\]]*\]", "*", e.path).lower())
    return pats


def _commented_entries(ctx: AuditContext) -> set[str]:
    """Paths in commented-out TOC lines (``#Core\\Old.lua``): deliberately disabled, not forgotten."""
    paths: list[str] = []
    for toc in ctx.addon.tocs:
        for raw in toc.raw_lines:
            s = raw.strip()
            if s.startswith("#") and not s.startswith("##"):
                path = s.lstrip("#").strip().split("[", 1)[0].strip().replace("\\", "/")
                if path.lower().endswith((".lua", ".xml")):
                    paths.append(path)
    out = {p.lower() for p in paths}
    # A disabled XML disables the scripts it would have loaded.
    for path in [p for p in paths if p.lower().endswith(".xml")]:
        xml = ctx.root / path
        if not xml.is_file():
            continue
        base = Path(path).parent.as_posix()
        for m in _XML_FILE_ATTR.finditer(xml.read_text(encoding="utf-8", errors="replace")):
            target = m.group(1).replace("\\", "/")
            out.add((target if base in ("", ".") else f"{base}/{target}").lower())
    return out


def _definition_only(lf: object) -> bool:
    """LuaLS ``---@meta`` stubs and files without any statement are not meant to be loaded."""
    head = "\n".join(lf.lines[:5])  # type: ignore[attr-defined]
    if re.search(r"^\s*---\s*@meta\b", head, re.M):
        return True
    ast = lf.ast  # type: ignore[attr-defined]
    return ast is not None and not ast.body.body


@rule("TOC006", "toc", "warn", "Lua file is never loaded",
      "A .lua file in the addon that no TOC or XML references never runs. Usually a forgotten TOC entry after "
      "adding a module (the code 'does nothing'), or dead code that should be deleted.", scope="addon",
      confidence="medium")
def unloaded_lua(ctx: AuditContext, emit: Emit) -> None:
    unloaded = [lf for lf in ctx.lua_files(loaded_only=False) if not lf.loaded and not ctx.config.is_excluded(lf.rel)]
    if not unloaded or _referenced_by_siblings(ctx):
        return  # another addon loads files from this folder; we cannot see its XML chain
    pm = load_pkgmeta(ctx.root)
    var_pats = _variable_patterns(ctx)
    commented = _commented_entries(ctx)
    sub_addons = {p.parent.relative_to(ctx.root).as_posix() for p in ctx.root.rglob("*.toc") if p.parent != ctx.root}
    for lf in unloaded:
        rel = lf.rel
        if pkg_ignored(pm, rel) or any(fnmatch.fnmatch(rel.lower(), p) for p in var_pats):
            continue
        if rel.lower() in commented or _definition_only(lf):
            continue
        if any(rel.startswith(d + "/") for d in sub_addons):
            continue  # belongs to a nested addon with its own TOC
        emit(None, f"{rel} is not listed in any TOC or XML file, so it never runs.", file=rel,
             fix_hint="Add it to the TOC in load order, include it from an XML file, or delete it.")


# --------------------------------------------------------------------------- saved variables


_DYNAMIC_G = re.compile(r"_G\s*\[[^\]]*\.\.|\bgetglobal\s*\(|\bsetglobal\s*\(|\bsetfenv\s*\(")
_CONCAT_PIECE = re.compile(r"\.\.\s*[\"']([A-Za-z0-9_]{2,})[\"']")


@rule("TOC007", "toc", "warn", "Declared SavedVariable is never used",
      "A SavedVariables name that no Lua file references is either a typo (the real table is not saved) or a "
      "leftover that keeps writing an empty file into WTF/.", scope="addon")
def unused_saved_variable(ctx: AuditContext, emit: Emit) -> None:
    sources = [lf.src for lf in ctx.lua_files() if lf.src]
    if not sources:
        return
    if any(_DYNAMIC_G.search(s) for s in sources):
        return  # names may be built at runtime (_G[addon .. "DB"]); cannot prove non-use
    if _loads_outside_root(ctx) or _referenced_by_siblings(ctx):
        return  # code shared with sibling addons is not in this context
    sources += [xf.text for xf in ctx.xml_files.values()]
    # `AceDB:New(addonName .. "DB")`: string pieces glued onto a runtime name.
    pieces = {m.group(1) for s in sources for m in _CONCAT_PIECE.finditer(s)}
    seen: set[str] = set()
    for toc in ctx.addon.tocs:
        for key in ("SavedVariables", "SavedVariablesPerCharacter"):
            names = toc.saved_variables if key == "SavedVariables" else toc.saved_variables_per_character
            for sv in names:
                sv = _strip_cond(sv)
                if not sv or sv in seen:
                    continue
                seen.add(sv)
                if any(p != sv and (sv.endswith(p) or sv.startswith(p)) for p in pieces):
                    continue
                pat = re.compile(rf"(?<!\w){re.escape(sv)}(?!\w)")
                if not any(pat.search(s) for s in sources):
                    emit(toc.line_of(key), f"SavedVariable '{sv}' is declared but never referenced in Lua.",
                         file=_toc_file(toc),
                         fix_hint="Fix the spelling to match the global your code uses, or remove it from the TOC.")


_DB_NAME = re.compile(r"(?:DB|Db|_db|Database|SavedVars|SavedVariables|Settings|Prefs)$")


def _is_name(node: Node | None, name: str) -> bool:
    return node is not None and node.kind == "Name" and node.id == name


def _sv_init_line(node: Node) -> int | None:
    """Line of an ``X = X or {...}`` / ``if not X then X = ... end`` initialisation of global X."""
    if node.kind != "Name" or not node.a.get("is_global") or not node.a.get("is_write"):
        return None
    assign = node.parent
    if assign is None or assign.kind != "Assign" or node not in assign.targets:
        return None
    idx = assign.targets.index(node)
    val = assign.values[idx] if idx < len(assign.values) else None
    if val is not None and val.kind == "BinOp" and val.op == "or" and _is_name(val.left, node.id):
        return assign.line
    for anc in assign.ancestors():
        if anc.kind == "Function":
            break
        if anc.kind == "If":
            cond = anc.clauses[0][0]
            if cond.kind == "UnOp" and cond.op == "not" and _is_name(cond.operand, node.id):
                return assign.line
            if (cond.kind == "BinOp" and cond.op == "==" and (_is_name(cond.left, node.id) and cond.right.kind == "Nil"
                                                              or _is_name(cond.right, node.id) and cond.left.kind == "Nil")):
                return assign.line
    return None


@rule("TOC008", "toc", "warn", "Database-like global is not declared in SavedVariables",
      "Code initialises a persistent-looking global (`MyAddonDB = MyAddonDB or {}`) that no TOC declares, so "
      "every setting is lost on /reload and logout.", scope="addon", confidence="medium")
def undeclared_saved_variable(ctx: AuditContext, emit: Emit) -> None:
    declared = {_strip_cond(s) for s in ctx.addon.saved_variables} | set(ctx.config.extra_globals)
    for name, sites in sorted(ctx.addon_globals.items()):
        if name in declared or not _DB_NAME.search(name) or name.isupper():
            continue
        for rel, node in sites:
            line = _sv_init_line(node)
            if line is not None:
                toc = ctx.addon.primary_toc
                emit(line, f"'{name}' is initialised like a saved database but is not in ## SavedVariables, so it "
                     "is never written to disk.", file=rel,
                     fix_hint=f"Add `## SavedVariables: {name}` (or SavedVariablesPerCharacter) to "
                              f"{toc.path.name if toc else 'the TOC'}, or make it a local if it is not meant to persist.")
                break


# --------------------------------------------------------------------------- directives


def _game_type_values(raw: str) -> list[str]:
    return [p.strip().lower() for p in _strip_cond(raw).split(",") if p.strip()]


@rule("TOC009", "toc", "warn", "Invalid AllowLoadGameType / ExcludeLoadGameType",
      "Unknown game types are ignored by the client (and if none is recognised the restriction is dropped), and a "
      "type that is both allowed and excluded means the addon never loads there.", scope="addon")
def game_types(ctx: AuditContext, emit: Emit) -> None:
    for toc in ctx.addon.tocs:
        allow: list[str] = []
        exclude: list[str] = []
        for key, bucket in (("AllowLoadGameType", allow), ("ExcludeLoadGameType", exclude)):
            raw = toc.get(key)
            if raw is None:
                continue
            line = toc.line_of(key)
            for v in _game_type_values(raw):
                bucket.append(v)
                if v not in GAME_TYPES:
                    emit(line, f"Unknown game type '{v}' in {key}.", file=_toc_file(toc),
                         fix_hint=f"Valid values: {', '.join(sorted(GAME_TYPES))}.")
        excluded = set(exclude)
        for fam, members in _FAMILIES.items():
            if fam in excluded:
                excluded |= members
        for v in allow:
            if v in excluded:
                emit(toc.line_of("ExcludeLoadGameType"), f"Game type '{v}' is both allowed and excluded, so the "
                     "addon never loads there.", file=_toc_file(toc), severity="error",
                     fix_hint=f"Remove '{v}' (or its family) from one of the two directives.")
        for entry in toc.files:
            for m in _INLINE_GT.finditer(entry.conditions):
                for v in _game_type_values(m.group(2)):
                    if v not in GAME_TYPES:
                        emit(entry.line, f"Unknown game type '{v}' in [{m.group(1)}LoadGameType] on {entry.path}.",
                             file=_toc_file(toc), fix_hint=f"Valid values: {', '.join(sorted(GAME_TYPES))}.")


@rule("TOC010", "toc", "error", "TOC line longer than 1024 characters",
      "The client only reads the first 1024 characters of a TOC line; the rest (a file path, part of the Notes, "
      "SavedVariables names) is silently dropped.", scope="addon")
def long_lines(ctx: AuditContext, emit: Emit) -> None:
    for toc in ctx.addon.tocs:
        for line in toc.long_lines:
            emit(line, f"Line is {len(toc.raw_lines[line - 1])} characters; everything after 1024 is ignored.",
                 file=_toc_file(toc), fix_hint="Shorten the line (split SavedVariables, shorten Notes or paths).")


@rule("TOC011", "toc", "info", "Missing recommended TOC metadata",
      "`Title`, `Notes` and `Version` are what users and addon managers see; without them the addon list shows "
      "the folder name and bug reports cannot say which version broke.", scope="addon")
def metadata(ctx: AuditContext, emit: Emit) -> None:
    # Per-client TOCs usually share one template: report each distinct gap once, on the first TOC that has it.
    groups: dict[tuple[str, ...], list[Toc]] = {}
    for toc in sorted(ctx.addon.tocs, key=lambda t: (t.suffix is not None, t.path.name)):
        keys = {k.lower().split("-", 1)[0] for k in toc.directives}
        missing = tuple(k for k in ("Title", "Notes", "Version") if k.lower() not in keys)
        if missing:
            groups.setdefault(missing, []).append(toc)
    for missing, tocs in groups.items():
        others = f" (and {len(tocs) - 1} other per-client TOC{'s' if len(tocs) > 2 else ''})" if len(tocs) > 1 else ""
        emit(1, f"{_toc_file(tocs[0])}{others} is missing {', '.join('## ' + m for m in missing)}.",
             file=_toc_file(tocs[0]),
             fix_hint="Add e.g. `## Title: MyAddon`, `## Notes: One-line description`, "
                      "`## Version: @project-version@` (the packager fills in the tag).")


@rule("TOC012", "toc", "info", "No addon list icon or category",
      "`## IconTexture` / `## IconAtlas` and `## Category` make the addon recognisable and filterable in the "
      "AddOns list and addon compartment.", scope="addon", confidence="low")
def icon_category(ctx: AuditContext, emit: Emit) -> None:
    toc = ctx.addon.primary_toc
    if toc is None:
        return
    keys = {k.lower().split("-", 1)[0] for k in toc.directives}
    missing = []
    if not keys & {"icontexture", "iconatlas"}:
        missing.append("## IconTexture (or ## IconAtlas)")
    if "category" not in keys:
        missing.append("## Category")
    if missing:
        emit(1, f"{_toc_file(toc)} has no {' or '.join(missing)}.", file=_toc_file(toc),
             fix_hint="e.g. `## IconTexture: Interface\\Icons\\INV_Misc_QuestionMark` and `## Category: Utility`.")


@rule("TOC013", "toc", "error", "Addon depends on itself",
      "Listing the addon's own name in `## Dependencies` / `## OptionalDeps` creates a dependency cycle; the "
      "client refuses to load it ('Dependency loop').", scope="addon")
def self_dependency(ctx: AuditContext, emit: Emit) -> None:
    name = ctx.addon.name.lower()
    for toc in ctx.addon.tocs:
        for key in toc.directives:
            lk = key.lower()
            if not (lk in ("dependencies", "requireddeps", "optionaldeps", "loadwith") or re.fullmatch(r"dep\w*", lk)):
                continue
            deps = [_strip_cond(d).lower() for d in toc.directives[key].split(",")]
            if name in deps:
                emit(toc.directive_lines[key], f"## {key} lists the addon itself ({ctx.addon.name}).",
                     file=_toc_file(toc), fix_hint=f"Remove {ctx.addon.name} from ## {key}.")
