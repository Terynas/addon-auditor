#!/usr/bin/env python3
"""Create rule fixtures and docs from a compact spec (used for the hand-written packs).

Spec module exposes ``SPECS = [{"id", "category", "title", "why", "bad": {file: text}, "good": {file: text},
"bad_doc"?, "good_doc"?, "refs"?}]``. Files named ``TOC`` are written as ``<folder>.toc``.

Usage: python scripts/new_fixture.py scripts/specs_lint.py [--force]
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOC = "## Interface: 16001, 120107\n## Title: Fixture\n## Notes: auditor fixture\n## Version: 1.0\n\ncore.lua\n"


def write_folder(folder: Path, files: dict[str, str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    files = dict(files)
    toc = files.pop("TOC", DEFAULT_TOC)
    (folder / f"{folder.name}.toc").write_text(toc, encoding="utf-8")
    for rel, text in files.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def main() -> int:
    spec_path = Path(sys.argv[1])
    force = "--force" in sys.argv
    spec = importlib.util.spec_from_file_location("specs", spec_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for s in mod.SPECS:
        base = ROOT / "tests" / "fixtures" / s["category"] / s["id"]
        if base.exists() and not force:
            print(f"skip {s['id']} (exists)")
            continue
        write_folder(base / "bad", s["bad"])
        write_folder(base / "good", s["good"])
        bad_src = s.get("bad_doc") or next((v for k, v in s["bad"].items() if k.endswith(".lua")), "")
        good_src = s.get("good_doc") or next((v for k, v in s["good"].items() if k.endswith(".lua")), "")
        refs = "\n".join(f"- {r}" for r in s.get("refs", [])) or "- First Timers `06-notes/addon-dev/`"
        doc = (f"# {s['id']}: {s['title']}\n\n**Category:** {s['category']}\n\n## Why\n\n{s['why'].strip()}\n\n"
               f"## Bad\n\n```lua\n{bad_src.strip()}\n```\n\n## Good\n\n```lua\n{good_src.strip()}\n```\n\n"
               f"## References\n\n{refs}\n")
        (ROOT / "rules-docs" / f"{s['id']}.md").write_text(doc, encoding="utf-8")
        print(f"wrote {s['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
