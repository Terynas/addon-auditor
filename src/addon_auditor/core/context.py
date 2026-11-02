"""Addon discovery and the shared audit context handed to every rule."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from . import suppress
from .config import Config, load_config
from .lua_ast import Comment, LuaSyntaxError, Node, parse
from .toc import Toc, parse_toc

XML_SCRIPT = re.compile(r"<Script\b[^>]*\bfile\s*=\s*\"([^\"]+)\"", re.I)
_LINE_COMMENT = re.compile(r"--(?!\[=*\[)(.*)$")
XML_INCLUDE = re.compile(r"<Include\b[^>]*\bfile\s*=\s*\"([^\"]+)\"", re.I)


@dataclass
class LuaFile:
    path: Path
    rel: str
    src: str
    lines: list[str]
    ast: Node | None
    comments: list[Comment]
    parse_error: LuaSyntaxError | None = None
    loaded: bool = True  # listed in a TOC / XML include
    suppressions: list[suppress.Suppression] = field(default_factory=list)

    def line(self, n: int) -> str:
        return self.lines[n - 1] if 0 < n <= len(self.lines) else ""


@dataclass
class XmlFile:
    path: Path
    rel: str
    text: str
    scripts: list[tuple[str, int]] = field(default_factory=list)  # (resolved rel, line)
    includes: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class Addon:
    root: Path
    name: str
    tocs: list[Toc]

    @property
    def primary_toc(self) -> Toc | None:
        for t in self.tocs:
            if t.suffix is None:
                return t
        return self.tocs[0] if self.tocs else None

    @property
    def saved_variables(self) -> list[str]:
        out: list[str] = []
        for t in self.tocs:
            for sv in t.saved_variables + t.saved_variables_per_character:
                if sv not in out:
                    out.append(sv)
        return out


class AuditError(Exception):
    pass


def find_addon_root(path: Path) -> Path:
    """Return the addon directory for ``path`` (dir containing ``<dirname>*.toc``)."""
    path = path.resolve()
    cur = path if path.is_dir() else path.parent
    for cand in [cur, *cur.parents]:
        if any(cand.glob("*.toc")):
            return cand
        if cand.parent == cand:
            break
    raise AuditError(f"no .toc file found at or above {path}")


def _norm(rel: str) -> str:
    parts: list[str] = []
    for p in rel.replace("\\", "/").split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/".join(parts)


def _ci_lookup(root: Path, rel: str) -> str | None:
    """Resolve rel case-insensitively (WoW on Windows is case-insensitive; Linux users get bitten)."""
    if (root / rel).exists():
        return rel
    cur = root
    out = []
    for part in rel.split("/"):
        if not cur.is_dir():
            return None
        match = next((c.name for c in cur.iterdir() if c.name.lower() == part.lower()), None)
        if match is None:
            return None
        out.append(match)
        cur = cur / match
    return "/".join(out)


class AuditContext:
    def __init__(self, root: Path, config: Config | None = None, profiles: list[str] | None = None) -> None:
        root = find_addon_root(root)
        tocs_paths = sorted(root.glob("*.toc"))
        name = root.name
        # Prefer TOCs that match the folder name; fall back to any.
        matching = [p for p in tocs_paths if p.stem == name or p.stem.startswith(name + "_") or p.stem.startswith(name + "-")]
        tocs = [parse_toc(p, name) for p in (matching or tocs_paths)]
        self.addon = Addon(root=root, name=name, tocs=tocs)
        self.config = config or load_config(root)
        self._profiles_override = profiles or self.config.profiles
        self.files: dict[str, LuaFile] = {}
        self.xml_files: dict[str, XmlFile] = {}
        self.load_order: list[str] = []
        self.missing_files: list[tuple[Toc | XmlFile, str, int]] = []
        self.case_mismatch: list[tuple[Toc | XmlFile, str, str, int]] = []
        self.probe: dict | None = None
        self._load()

    # ---------------------------------------------------------------- loading
    @property
    def root(self) -> Path:
        return self.addon.root

    def _load(self) -> None:
        seen: set[str] = set()
        for toc in self.addon.tocs:
            for entry in toc.files:
                if "[" in entry.path:  # [Family]/[Game] variables -- cannot resolve statically
                    continue
                self._load_entry(toc, _norm(entry.path), entry.line, seen)
        # Unlisted Lua files (not loaded by any TOC/XML)
        for p in sorted(self.root.rglob("*.lua")):
            rel = p.relative_to(self.root).as_posix()
            if rel in self.files or self.config.is_excluded(rel):
                continue
            self._add_lua(rel, loaded=False)

    def _load_entry(self, owner: Toc | XmlFile, rel: str, line: int, seen: set[str]) -> None:
        actual = _ci_lookup(self.root, rel)
        if actual is None:
            self.missing_files.append((owner, rel, line))
            return
        if actual != rel:
            self.case_mismatch.append((owner, rel, actual, line))
        if actual in seen:
            return
        seen.add(actual)
        if self.config.is_excluded(actual):
            return
        lower = actual.lower()
        if lower.endswith(".lua"):
            self._add_lua(actual, loaded=True)
            self.load_order.append(actual)
        elif lower.endswith(".xml"):
            self._add_xml(actual, seen)

    def _add_lua(self, rel: str, loaded: bool) -> None:
        path = self.root / rel
        src = path.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        ast: Node | None = None
        comments: list[Comment] = []
        err: LuaSyntaxError | None = None
        try:
            ast, comments = parse(src)
        except LuaSyntaxError as e:
            err = e
            comments = [Comment(m.group(1), i, i) for i, text in enumerate(lines, start=1)
                        if (m := _LINE_COMMENT.search(text))]
        lf = LuaFile(path, rel, src, lines, ast, comments, err, loaded)
        lf.suppressions = suppress.collect(comments, lines)
        self.files[rel] = lf

    def _add_xml(self, rel: str, seen: set[str]) -> None:
        path = self.root / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        xf = XmlFile(path, rel, text)
        self.xml_files[rel] = xf
        base = Path(rel).parent.as_posix()
        for regex, bucket in ((XML_INCLUDE, xf.includes), (XML_SCRIPT, xf.scripts)):
            for m in regex.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                target = _norm(f"{base}/{m.group(1)}" if base not in ("", ".") else m.group(1))
                bucket.append((target, line))
        # Preserve document order between Include and Script.
        events = sorted([(ln, t) for t, ln in xf.includes] + [(ln, t) for t, ln in xf.scripts])
        for ln, target in events:
            self._load_entry(xf, target, ln, seen)

    # ---------------------------------------------------------------- queries
    @cached_property
    def profiles(self) -> set[str]:
        if self._profiles_override:
            return set(self._profiles_override)
        out: set[str] = set()
        for t in self.addon.tocs:
            out |= t.profiles
        return out or {"mainline"}

    def has_profile(self, *names: str) -> bool:
        return bool(self.profiles & set(names))

    def lua_files(self, loaded_only: bool = True) -> list[LuaFile]:
        return [f for f in self.files.values() if (f.loaded or not loaded_only)]

    def parsed_files(self) -> list[LuaFile]:
        return [f for f in self.lua_files() if f.ast is not None]

    def source_line(self, rel: str, line: int) -> str | None:
        lf = self.files.get(rel)
        if lf:
            return lf.line(line)
        if rel.lower().endswith(".toc"):
            for t in self.addon.tocs:
                if t.path.name == rel and 0 < line <= len(t.raw_lines):
                    return t.raw_lines[line - 1]
        xf = self.xml_files.get(rel)
        if xf:
            xl = xf.text.splitlines()
            return xl[line - 1] if 0 < line <= len(xl) else None
        return None

    @cached_property
    def addon_globals(self) -> dict[str, list[tuple[str, Node]]]:
        """Global names written anywhere in the addon -> [(file, node)]."""
        out: dict[str, list[tuple[str, Node]]] = {}
        for lf in self.parsed_files():
            assert lf.ast is not None
            for node in lf.ast.walk():
                if node.kind == "Name" and node.a.get("is_global") and node.a.get("is_write"):
                    out.setdefault(node.id, []).append((lf.rel, node))
        return out

    @cached_property
    def xml_global_names(self) -> set[str]:
        names: set[str] = set()
        for xf in self.xml_files.values():
            for m in re.finditer(r"\bname\s*=\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", xf.text):
                names.add(m.group(1))
        return names

    @cached_property
    def api(self):  # type: ignore[no-untyped-def]
        from ..adapters.api_index import ApiIndex

        return ApiIndex.for_profiles(self.profiles)
