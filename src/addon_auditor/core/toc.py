"""TOC file parsing and client profile detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# TOC filename suffixes Blizzard recognises for per-client TOCs.
TOC_SUFFIXES = {
    "mainline": "mainline", "standard": "mainline",
    "vanilla": "classic-era", "classic": "classic", "tbc": "classic", "bcc": "classic", "wrath": "classic",
    "wotlkc": "classic", "cata": "classic", "mists": "classic", "forever": "forever", "camelot": "forever",
}

PROFILES = ("forever", "classic-era", "classic", "mainline")


def profile_for_interface(iface: int) -> str:
    if 16000 <= iface < 17000:
        return "forever"
    if iface < 20000:
        return "classic-era"
    if iface < 110000:
        return "classic"
    return "mainline"


@dataclass
class TocEntry:
    path: str  # as written (backslashes normalised to /)
    line: int
    conditions: str = ""  # e.g. "[AllowLoadGameType mainline]"


@dataclass
class Toc:
    path: Path
    suffix: str | None
    directives: dict[str, str] = field(default_factory=dict)
    directive_lines: dict[str, int] = field(default_factory=dict)
    files: list[TocEntry] = field(default_factory=list)
    long_lines: list[int] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

    def get(self, key: str) -> str | None:
        lk = key.lower()
        for k, v in self.directives.items():
            if k.lower() == lk:
                return v
        return None

    def line_of(self, key: str) -> int | None:
        lk = key.lower()
        for k, v in self.directive_lines.items():
            if k.lower() == lk:
                return v
        return None

    @property
    def interfaces(self) -> list[int]:
        raw = self.get("Interface") or ""
        out = []
        for part in re.split(r"[,\s]+", raw):
            if part.isdigit():
                out.append(int(part))
        return out

    def _csv(self, key: str) -> list[str]:
        raw = self.get(key) or ""
        return [p.strip() for p in raw.split(",") if p.strip()]

    @property
    def saved_variables(self) -> list[str]:
        return self._csv("SavedVariables")

    @property
    def saved_variables_per_character(self) -> list[str]:
        return self._csv("SavedVariablesPerCharacter")

    @property
    def dependencies(self) -> list[str]:
        return self._csv("Dependencies") + self._csv("RequiredDeps") + self._csv("Dep")

    @property
    def optional_deps(self) -> list[str]:
        return self._csv("OptionalDeps")

    @property
    def allow_game_types(self) -> list[str]:
        return [p.lower() for p in self._csv("AllowLoadGameType")]

    @property
    def exclude_game_types(self) -> list[str]:
        return [p.lower() for p in self._csv("ExcludeLoadGameType")]

    @property
    def profiles(self) -> set[str]:
        out = {profile_for_interface(i) for i in self.interfaces}
        if self.suffix and self.suffix.lower() in TOC_SUFFIXES:
            out = {TOC_SUFFIXES[self.suffix.lower()]} if not out else out
        # Forever builds advertise themselves through AllowLoadGameType too.
        if {"forever", "camelot"} & set(self.allow_game_types):
            out.add("forever")
        return out


def parse_toc(path: Path, addon_name: str) -> Toc:
    stem = path.stem
    suffix = None
    if stem != addon_name and stem.startswith(addon_name + "_"):
        suffix = stem[len(addon_name) + 1:]
    elif stem != addon_name and stem.startswith(addon_name + "-"):
        suffix = stem[len(addon_name) + 1:]
    toc = Toc(path=path, suffix=suffix)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    toc.raw_lines = text.splitlines()
    for i, raw in enumerate(toc.raw_lines, start=1):
        if len(raw) > 1024:
            toc.long_lines.append(i)
        line = raw.strip()
        if not line:
            continue
        if line.startswith("##"):
            body = line[2:].strip()
            if ":" in body:
                key, _, value = body.partition(":")
                key = key.strip()
                toc.directives[key] = value.strip()
                toc.directive_lines[key] = i
            continue
        if line.startswith("#"):
            continue
        cond = ""
        m = re.match(r"^(.*?)\s*(\[.*\])\s*$", line)
        if m and not m.group(1).endswith("]"):
            line, cond = m.group(1).strip(), m.group(2)
        toc.files.append(TocEntry(line.replace("\\", "/"), i, cond))
    return toc
