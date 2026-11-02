"""PACKAGING rule pack: what actually ends up in the release zip.

The BigWigs / CurseForge packager reads ``.pkgmeta`` (YAML). We only need a handful of keys, so it is parsed
line-by-line instead of pulling in a YAML dependency. The packager always drops dot-files and dot-folders.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core.context import AuditContext
from ..core.finding import Emit, rule
from ..core.toc import TOC_SUFFIXES

PKGMETA_NAMES = (".pkgmeta", "pkgmeta.yaml", "pkgmeta.yml")
LIB_DIRS = ("libs", "lib", "libraries")


@dataclass
class PkgMeta:
    path: Path
    rel: str
    lines: list[str]
    package_as: str | None = None
    package_as_line: int | None = None
    ignore: list[tuple[str, int]] = field(default_factory=list)
    ignore_line: int | None = None
    externals: list[tuple[str, int]] = field(default_factory=list)
    manual_changelog: str | None = None
    tab_lines: list[int] = field(default_factory=list)


def _scalar(value: str) -> str:
    value = re.sub(r"\s+#.*$", "", value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def load_pkgmeta(root: Path) -> PkgMeta | None:
    path = next((root / n for n in PKGMETA_NAMES if (root / n).is_file()), None)
    if path is None:
        return None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    pm = PkgMeta(path, path.name, lines)
    section: str | None = None
    for i, raw in enumerate(lines, start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            pm.tab_lines.append(i)
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            key, _, value = stripped.partition(":")
            key, value = key.strip().lower(), _scalar(value)
            section = key
            if key == "package-as":
                pm.package_as, pm.package_as_line = value or None, i
            elif key == "ignore":
                pm.ignore_line = i
                if value.startswith("[") and value.endswith("]"):
                    pm.ignore += [(_scalar(v), i) for v in value[1:-1].split(",") if _scalar(v)]
            elif key == "manual-changelog" and value:
                pm.manual_changelog = value
            continue
        if section == "ignore" and stripped.startswith("-"):
            item = _scalar(stripped[1:])
            if item:
                pm.ignore.append((item, i))
        elif section == "externals" and indent <= 4 and not stripped.startswith("-"):
            key = stripped.split(":", 1)[0].strip().strip("\"'")
            if key and key.lower() not in ("url", "tag", "branch", "commit", "type", "curse-slug", "path"):
                pm.externals.append((key.replace("\\", "/").rstrip("/"), i))
        elif section == "manual-changelog" and stripped.lower().startswith("filename:"):
            pm.manual_changelog = _scalar(stripped.split(":", 1)[1])
    return pm


def pkg_ignored(pm: PkgMeta | None, rel: str) -> bool:
    """Would the packager drop ``rel``? Dot-paths are always dropped; ``ignore`` entries are globs/prefixes."""
    rel = rel.replace("\\", "/")
    if any(part.startswith(".") for part in rel.split("/")):
        return True
    if pm is None:
        return False
    for pat, _ in pm.ignore:
        pat = pat.replace("\\", "/").strip("/")
        if not pat:
            continue
        if fnmatch.fnmatch(rel, pat) or rel == pat or rel.startswith(pat + "/"):
            return True
        if "/" not in pat and fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pat):
            return True
    return False


def under_external(pm: PkgMeta | None, rel: str) -> bool:
    if pm is None:
        return False
    low = rel.replace("\\", "/").lower()
    return any(low == e.lower() or low.startswith(e.lower() + "/") for e, _ in pm.externals)


def _shipped_files(ctx: AuditContext, pm: PkgMeta | None) -> list[tuple[str, int]]:
    """(rel, size) of every file the packager would include (dot-paths and ignored paths removed)."""
    root = ctx.root
    out: list[tuple[str, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath).relative_to(root).as_posix()
        base = "" if base == "." else base
        dirnames[:] = [d for d in dirnames if not pkg_ignored(pm, f"{base}/{d}".lstrip("/"))]
        for fn in filenames:
            rel = f"{base}/{fn}".lstrip("/")
            if fn in PKGMETA_NAMES or pkg_ignored(pm, rel):
                continue
            try:
                out.append((rel, (Path(dirpath) / fn).stat().st_size))
            except OSError:
                continue
    return out


def _toc_names(ctx: AuditContext) -> set[str]:
    names = {ctx.addon.name}
    for p in ctx.root.glob("*.toc"):
        stem = p.stem
        m = re.match(r"^(.+?)[_-]([A-Za-z]+)$", stem)
        if m and m.group(2).lower() in TOC_SUFFIXES:
            stem = m.group(1)
        names.add(stem)
    return names


# --------------------------------------------------------------------------- rules


@rule("PKG001", "packaging", "error", ".pkgmeta is malformed or packages under the wrong name",
      "`package-as` must equal the addon folder / TOC name, and YAML forbids tab indentation. Either mistake "
      "produces a zip the client cannot load (or a failed release build).", scope="addon")
def pkgmeta_sanity(ctx: AuditContext, emit: Emit) -> None:
    pm = load_pkgmeta(ctx.root)
    if pm is None:
        return
    for ln in pm.tab_lines[:5]:
        emit(ln, f"{pm.rel} uses a tab for indentation; YAML only allows spaces and the packager will fail to parse it.",
             file=pm.rel, fix_hint="Indent with spaces (two per level).")
    if pm.package_as is None:
        return
    names = _toc_names(ctx)
    if pm.package_as not in names:
        emit(pm.package_as_line, f"package-as: {pm.package_as} does not match the TOC name "
             f"({', '.join(sorted(names))}); the packaged folder name will not match its .toc and WoW ignores it.",
             file=pm.rel, fix_hint=f"Set `package-as: {ctx.addon.name}` (folder, TOC and package-as must agree).")


_JUNK_DIRS = {
    "node_modules": "node_modules (npm dependencies)", "__pycache__": "Python bytecode cache",
    ".vscode": "VS Code settings", ".idea": "JetBrains IDE settings",
}
_TEST_DIRS = {"tests", "test", "spec", "specs"}
_JUNK_FILES = {
    "*.psd": "Photoshop source", "*.xcf": "GIMP source", "*.kra": "Krita source", "*.blend": "Blender source",
    "*.blend1": "Blender backup", "*.zip": "archive", "*.rar": "archive", "*.7z": "archive",
    "*.tar.gz": "archive", "*.bak": "backup file", ".DS_Store": "macOS Finder metadata",
    "Thumbs.db": "Windows thumbnail cache", "desktop.ini": "Windows folder metadata",
}


def _is_lib_dir(rel: str) -> bool:
    return rel.split("/", 1)[0].lower() in LIB_DIRS


@rule("PKG002", "packaging", "warn", "Development or junk files would ship",
      "Editor folders, art sources, archives, OS metadata and test suites end up in the user's AddOns folder "
      "unless `.pkgmeta` ignores them.", scope="addon", confidence="medium")
def junk_files(ctx: AuditContext, emit: Emit) -> None:
    root = ctx.root
    pm = load_pkgmeta(root)
    # Without .pkgmeta but inside a git checkout, dot-files are almost certainly dropped by whatever zips it.
    hand_packaged = pm is None and not (root / ".git").exists()
    found: dict[str, list[str]] = {}
    tests: list[str] = []

    def dropped(rel: str) -> bool:
        if not hand_packaged and any(p.startswith(".") for p in rel.split("/")):
            return True
        return pm is not None and pkg_ignored(pm, rel)

    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath).relative_to(root).as_posix()
        base = "" if base == "." else base
        keep = []
        for d in sorted(dirnames):
            rel = f"{base}/{d}".lstrip("/")
            if d == ".git" or dropped(rel) or _is_lib_dir(rel):
                continue
            if d in _JUNK_DIRS:
                found.setdefault(_JUNK_DIRS[d], []).append(rel + "/")
            elif d.lower() in _TEST_DIRS and not base:
                tests.append(rel + "/")
            else:
                keep.append(d)
        dirnames[:] = keep
        for fn in sorted(filenames):
            rel = f"{base}/{fn}".lstrip("/")
            if dropped(rel):
                continue
            kind = next((k for pat, k in _JUNK_FILES.items() if fnmatch.fnmatch(fn, pat)), None)
            if kind:
                found.setdefault(kind, []).append(rel)
    hint = (f"Add these paths to the `ignore:` list in {pm.rel}." if pm else
            "Add a `.pkgmeta` with an `ignore:` list (BigWigs packager), or delete the files before zipping.")
    for kind, paths in found.items():
        shown = ", ".join(paths[:5]) + (f" (+{len(paths) - 5} more)" if len(paths) > 5 else "")
        emit(None, f"{kind} would ship in the release: {shown}", file=paths[0], fix_hint=hint)
    for rel in tests:
        if pm is not None:
            emit(None, f"Test folder {rel} is not in the {pm.rel} ignore list and would ship to users.",
                 file=rel, fix_hint=hint)
        else:
            emit(None, f"Test folder {rel} has no .pkgmeta ignore entry; it ships unless your packaging script "
                 "strips it.", file=rel, severity="info", confidence="low", fix_hint=hint)


_LICENSE = re.compile(r"^(licen[cs]e|copying)([._-].*)?$", re.I)
_CHANGELOG = re.compile(r"^(changelog|changes|history|news)([._-].*)?$", re.I)


@rule("PKG003", "packaging", "info", "Missing LICENSE or CHANGELOG",
      "Distribution sites and users expect a license (so others know what they may do with the code) and a "
      "changelog (so users know what changed).", scope="addon")
def license_changelog(ctx: AuditContext, emit: Emit) -> None:
    names = [p.name for p in ctx.root.iterdir() if p.is_file()]
    pm = load_pkgmeta(ctx.root)
    if not any(_LICENSE.match(n) for n in names):
        emit(None, "No LICENSE file at the addon root.",
             fix_hint="Add a LICENSE (e.g. MIT, GPL-3.0, or All Rights Reserved) so the terms are explicit.")
    has_changelog = any(_CHANGELOG.match(n) for n in names) or bool(
        pm and pm.manual_changelog and (ctx.root / pm.manual_changelog).is_file())
    if not has_changelog:
        emit(None, "No CHANGELOG at the addon root.",
             fix_hint="Add CHANGELOG.md (and `manual-changelog: CHANGELOG.md` in .pkgmeta) to tell users what changed.")


@rule("PKG004", "packaging", "warn", "Release package is unusually large",
      "Large addons download slowly, bloat the client's memory if the assets load, and usually mean source art, "
      "videos or docs are shipping by accident.", scope="addon")
def package_size(ctx: AuditContext, emit: Emit) -> None:
    pm = load_pkgmeta(ctx.root)
    limit_mb = ctx.config.threshold("package_size_mb_warn")
    if limit_mb <= 0:
        return
    files = _shipped_files(ctx, pm)
    total = sum(s for _, s in files)
    if total <= limit_mb * 1024 * 1024:
        return
    biggest = sorted(files, key=lambda x: -x[1])[:3]
    top = ", ".join(f"{r} ({s / 1048576:.1f} MB)" for r, s in biggest)
    emit(None, f"Shipped files total {total / 1048576:.1f} MB (threshold {limit_mb:g} MB). Largest: {top}",
         fix_hint="Ignore docs/source assets in .pkgmeta, compress textures (BLP/TGA at power-of-two sizes), "
                  "or raise thresholds.package_size_mb_warn in .addon-auditor.toml.")


_LIB_VERSION = re.compile(r"NewLibrary\s*\(|\bMINOR\s*=\s*\d|_MINOR\s*=\s*\d|\$Revision|@project-revision@|"
                          r"^##\s*Version\s*:", re.I | re.M)


@rule("PKG005", "packaging", "info", "Vendored library without a version marker",
      "A library copied into Libs/ with no LibStub MINOR, TOC version or .pkgmeta external is hard to update "
      "and may silently override (or be overridden by) other addons' copies.", scope="addon", confidence="low")
def lib_versions(ctx: AuditContext, emit: Emit) -> None:
    pm = load_pkgmeta(ctx.root)
    for libdir in sorted(p for p in ctx.root.iterdir() if p.is_dir() and p.name.lower() in LIB_DIRS):
        for lib in sorted(p for p in libdir.iterdir() if p.is_dir()):
            rel = lib.relative_to(ctx.root).as_posix()
            if under_external(pm, rel) or pkg_ignored(pm, rel):
                continue
            sources = [f for f in lib.rglob("*") if f.is_file() and f.suffix.lower() in (".lua", ".toc")]
            if not sources:
                continue
            if any(_LIB_VERSION.search(f.read_text(encoding="utf-8", errors="replace")) for f in sources):
                continue
            emit(None, f"{rel}/ has no version marker (LibStub MINOR, ## Version, or .pkgmeta external).",
                 file=rel, fix_hint="Pull the library via `externals:` in .pkgmeta, or note its upstream version.")
