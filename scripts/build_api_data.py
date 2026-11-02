#!/usr/bin/env python3
"""Build bundled API name data (src/addon_auditor/data/api-<profile>.json.gz).

Only identifiers are stored (global names, namespace members, deprecated names) -- no API docs.

Sources:
  forever : WowForeverAPI.lua dump + Blizzard UI source for the Forever client
  mainline: Ketho vscode-wow-api Annotations (MIT) + Blizzard UI source for Midnight

Usage:
  python scripts/build_api_data.py --first-timers "../First Timers"
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from addon_auditor.core.lua_ast import LuaSyntaxError, dotted_name, parse  # noqa: E402

DATA = ROOT / "src" / "addon_auditor" / "data"
XML_NAME = re.compile(r"<(?:Frame|Button|CheckButton|EditBox|ScrollFrame|StatusBar|Slider|GameTooltip|"
                      r"MessageFrame|ScrollingMessageFrame|Model|PlayerModel|Cooldown|ColorSelect|FontString|"
                      r"Texture|Font|SimpleHTML|MovieFrame|Minimap|DressUpModel|TabardModel|CinematicModel)\b"
                      r"[^>]*?\bname=\"([A-Za-z_][A-Za-z0-9_]*)\"")
FN_LINE = re.compile(r"^function\s+([A-Za-z_][A-Za-z0-9_]*)(?:[.:]([A-Za-z_][A-Za-z0-9_]*))?", re.M)
ASSIGN_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))?\s*=[^=]", re.M)


class Collector:
    def __init__(self) -> None:
        self.globals: set[str] = set()
        self.members: dict[str, set[str]] = {}
        self.deprecated: set[str] = set()

    def add_member(self, ns: str, member: str) -> None:
        self.globals.add(ns)
        self.members.setdefault(ns, set()).add(member)

    def scan_annotation_text(self, text: str, deprecated: bool = False) -> None:
        for m in FN_LINE.finditer(text):
            ns, member = m.group(1), m.group(2)
            if member:
                self.add_member(ns, member)
                if deprecated:
                    self.deprecated.add(f"{ns}.{member}")
            else:
                self.globals.add(ns)
                if deprecated:
                    self.deprecated.add(ns)
        for m in ASSIGN_LINE.finditer(text):
            ns, member = m.group(1), m.group(2)
            if ns in ("local", "return"):
                continue
            if member:
                self.add_member(ns, member)
            else:
                self.globals.add(ns)

    def scan_blizzard_lua(self, src: str) -> None:
        try:
            chunk, _ = parse(src)
        except LuaSyntaxError:
            self.scan_annotation_text(src)
            return
        for node in chunk.walk():
            if node.kind == "FunctionDecl":
                name = dotted_name(node.target)
                if not name:
                    continue
                parts = name.split(".")
                root = node.target
                while root.kind == "Index":
                    root = root.obj
                if root.kind != "Name" or not root.a.get("is_global"):
                    continue
                if len(parts) == 1:
                    self.globals.add(parts[0])
                elif len(parts) == 2:
                    self.add_member(parts[0], parts[1])
            elif node.kind == "Assign":
                for tg in node.targets:
                    if tg.kind == "Name" and tg.a.get("is_global"):
                        self.globals.add(tg.id)
                    elif tg.kind == "Index" and tg.obj.kind == "Name" and tg.obj.a.get("is_global") \
                            and tg.key.kind == "String":
                        self.add_member(tg.obj.id, str(tg.key.value))

    def scan_blizzard_tree(self, root: Path) -> None:
        for path in root.rglob("*.lua"):
            self.scan_blizzard_lua(path.read_text(encoding="utf-8", errors="replace"))
        for path in root.rglob("*.xml"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in XML_NAME.finditer(text):
                self.globals.add(m.group(1))

    def dump(self, profile: str, sources: list[str]) -> dict:
        return {
            "profile": profile,
            "generated": date.today().isoformat(),
            "sources": sources,
            "globals": sorted(self.globals),
            "members": {k: sorted(v) for k, v in sorted(self.members.items())},
            "deprecated": sorted(self.deprecated),
        }


def write(profile: str, payload: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / f"api-{profile}.json.gz"
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print(f"{out.relative_to(ROOT)}: {len(payload['globals'])} globals, "
          f"{sum(len(v) for v in payload['members'].values())} members, {len(payload['deprecated'])} deprecated")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-timers", required=True, type=Path)
    args = ap.parse_args()
    ft: Path = args.first_timers

    forever = Collector()
    dump = ft / "02-api-docs" / "forever-api-dump" / "types" / "WowForeverAPI.lua"
    forever.scan_annotation_text(dump.read_text(encoding="utf-8", errors="replace"))
    forever.scan_blizzard_tree(ft / "03-blizzard-source" / "forever" / "Interface")
    write("forever", forever.dump("forever", ["WowForeverAPI.lua (Atraeau/WoW-Addons)", "Blizzard UI source (Forever)"]))

    mainline = Collector()
    ann = ft / "02-api-docs" / "vscode-wow-api" / "Annotations"
    for path in ann.rglob("*.lua"):
        mainline.scan_annotation_text(path.read_text(encoding="utf-8", errors="replace"),
                                      deprecated="Deprecated" in path.as_posix())
    mainline.scan_blizzard_tree(ft / "03-blizzard-source" / "midnight-live" / "Interface")
    write("mainline", mainline.dump("mainline", ["Ketho/vscode-wow-api Annotations (MIT)", "Blizzard UI source (Midnight)"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
