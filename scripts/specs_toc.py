#!/usr/bin/env python3
"""Fixture/doc specs for TOC and PKG rules.

Self-contained writer (TOC rules care about folder and TOC names, which ``new_fixture.py`` does not model):
each side (``bad`` / ``good``) is ``{"addon"?: folder, "toc_name"?: name, "files": {rel: text}}``. ``TOC`` in
``files`` is the TOC body (default: the standard fixture TOC). With ``addon`` the mini addon lives in
``bad/<addon>/``.

Usage: python scripts/specs_toc.py [--force]
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOC = "## Interface: 16001, 120107\n## Title: Fixture\n## Notes: auditor fixture\n## Version: 1.0\n\ncore.lua\n"
CORE = "local addonName, ns = ...\nns.ready = true\n"
TOC_REF = "First Timers `06-notes/addon-dev/toc-format.md`"
WIKI_REF = "First Timers `01-guides/wiki/02-toc-format.md` (Warcraft Wiki: TOC format)"
PKG_REF = "First Timers `06-notes/addon-dev/distribution-and-packaging.md`"
SV_REF = "First Timers `06-notes/addon-dev/savedvariables-and-load-order.md`"


def toc(*directives: str, files: str = "core.lua") -> str:
    head = "\n".join(f"## {d}" for d in directives)
    return f"{head}\n\n{files}\n"


STD = ("Interface: 16001, 120107", "Title: Fixture", "Notes: auditor fixture", "Version: 1.0")

SPECS: list[dict] = [
    {
        "id": "TOC001", "category": "toc", "title": "TOC file name does not match the addon folder",
        "why": "WoW looks for `<Folder>.toc`, or `<Folder>_<Suffix>.toc` where the suffix names a client "
               "(`Mainline`, `Standard`, `Forever`, `Vanilla`, `TBC`, `Wrath`, `Cata`, `Mists`, `Classic`, ...). "
               "Any other TOC is ignored. If no TOC matches, the addon is simply missing from the AddOns list -- "
               "the most common 'my addon does not show up' report. Names are case-sensitive on Linux/macOS.",
        "bad": {"addon": "MyAddon", "toc_name": "MyAddOn.toc", "files": {"core.lua": CORE}},
        "good": {"addon": "MyAddon", "files": {"core.lua": CORE, "MyAddon_Vanilla.toc": toc(
            "Interface: 11508", "Title: MyAddon", "Notes: n", "Version: 1.0")}},
        "bad_doc": "MyAddon/\n  MyAddOn.toc      <- case differs from the folder: never read\n  core.lua",
        "good_doc": "MyAddon/\n  MyAddon.toc\n  MyAddon_Vanilla.toc  <- known client suffix\n  core.lua",
        "lang": "text", "refs": [TOC_REF, WIKI_REF],
    },
    {
        "id": "TOC002", "category": "toc", "title": "Missing or invalid ## Interface",
        "why": "`## Interface` tells each client whether the addon is up to date. It must be one or more "
               "comma-separated integers (`12.1.7` is written `120107`, Forever 1.60.1 is `16001`). A missing or "
               "malformed value makes the addon 'out of date' everywhere. `## Interface: 0` is accepted: it is "
               "the idiom for a fallback TOC that only shows an 'unsupported client' message.",
        "bad": {"files": {"TOC": toc("Interface: 1.15.7", "Title: Fixture", "Notes: n", "Version: 1.0"),
                          "core.lua": CORE}},
        "good": {"files": {"core.lua": CORE}},
        "bad_doc": "## Interface: 1.15.7\n## Title: Fixture",
        "good_doc": "## Interface: 11508, 16001, 120107\n## Title: Fixture",
        "lang": "ini", "refs": [TOC_REF],
    },
    {
        "id": "TOC003", "category": "toc", "title": "Per-client TOC suffix does not match its Interface",
        "why": "The client picks `_Vanilla.toc` on Classic Era, `_Mists.toc` on Mists Classic, `_Mainline.toc` on "
               "the Mainline family (Midnight and Forever), and so on. A suffixed TOC whose Interface numbers all "
               "belong to a different client is a copy-paste slip: the addon shows as out of date on the client "
               "that actually reads it.",
        "bad": {"addon": "MyAddon", "files": {"core.lua": CORE, "MyAddon_Vanilla.toc": toc(
            "Interface: 120107", "Title: MyAddon", "Notes: n", "Version: 1.0")}},
        "good": {"addon": "MyAddon", "files": {"core.lua": CORE, "MyAddon_Vanilla.toc": toc(
            "Interface: 11508", "Title: MyAddon", "Notes: n", "Version: 1.0")}},
        "bad_doc": "# MyAddon_Vanilla.toc\n## Interface: 120107",
        "good_doc": "# MyAddon_Vanilla.toc\n## Interface: 11508",
        "lang": "ini", "refs": [TOC_REF, WIKI_REF],
    },
    {
        "id": "TOC004", "category": "toc", "title": "TOC / XML lists a file that does not exist",
        "why": "A missing file is skipped with a 'file not found' log line. Everything it would have defined is "
               "nil, so the first file that uses it throws. Typical after renaming or moving a file. Paths under "
               "a `.pkgmeta` `externals:` entry are not reported (the packager fetches them). Paths that climb "
               "into a sibling addon (`..\\BagBrother\\core.xml`) are resolved on disk and, if absent, reported "
               "as a low-confidence warning.",
        "bad": {"files": {"TOC": toc(*STD, files="core.lua\nModules\\Missing.lua"), "core.lua": CORE}},
        "good": {"files": {"TOC": toc(*STD, files="Libs\\LibStub\\LibStub.lua\ncore.lua"), "core.lua": CORE,
                           ".pkgmeta": "package-as: good\n\nexternals:\n  Libs/LibStub: https://repos.wowace.com/wow/libstub/trunk\n"}},
        "bad_doc": "core.lua\nModules\\Missing.lua   <- not on disk",
        "good_doc": "Libs\\LibStub\\LibStub.lua   <- fetched via .pkgmeta externals\ncore.lua",
        "lang": "ini", "refs": [TOC_REF],
    },
    {
        "id": "TOC005", "category": "toc", "title": "File path case differs from the file on disk",
        "why": "Windows resolves `Core.lua` to `core.lua`, but Linux (Wine/Proton players), case-sensitive macOS "
               "volumes and some packaging tools do not. The file then fails to load only for some users, which "
               "is very hard to debug from a bug report.",
        "bad": {"files": {"TOC": toc(*STD, files="Core.lua"), "core.lua": CORE}},
        "good": {"files": {"core.lua": CORE}},
        "bad_doc": "Core.lua      <- file on disk is core.lua",
        "good_doc": "core.lua",
        "lang": "ini", "refs": [TOC_REF],
    },
    {
        "id": "TOC006", "category": "toc", "title": "Lua file is never loaded",
        "why": "WoW only runs files listed in a TOC or included from a loaded XML file. A new module that was "
               "never added to the TOC 'does nothing' with no error. Libraries, tests and paths excluded in "
               "`.addon-auditor.toml`, `.pkgmeta` ignores, nested addons with their own TOC, files matched by "
               "TOC variables (`[Family]\\File.lua`), files in commented-out TOC lines (`#Old.lua`, including "
               "scripts of a commented-out XML), LuaLS `---@meta` stubs, and addons whose files a sibling addon "
               "loads via `..\\ThisAddon\\` paths are not reported.",
        "bad": {"files": {"core.lua": CORE, "Extra.lua": "local _, ns = ...\nns.extra = true\n"}},
        "good": {"files": {"TOC": toc(*STD, files="core.lua\nExtra.lua\n#Old.lua"), "core.lua": CORE,
                           "Extra.lua": "local _, ns = ...\nns.extra = true\n",
                           "Old.lua": "-- disabled on purpose via the commented TOC line\nlocal x = 1\n",
                           "Types/Defs.lua": "---@meta _\n---@class FixtureNS\nlocal FixtureNS = {}\n",
                           "spec/core_spec.lua": "describe('x', function() end)\n"}},
        "bad_doc": "# MyAddon.toc lists only core.lua\n# Extra.lua exists on disk but never runs",
        "good_doc": "core.lua\nExtra.lua",
        "lang": "ini", "refs": [TOC_REF],
    },
    {
        "id": "TOC007", "category": "toc", "title": "Declared SavedVariable is never used",
        "why": "The client saves exactly the globals named in `## SavedVariables`. If the code uses a different "
               "spelling (`MyAddon_DB` vs `MyAddonDB`), the real data is never saved and the declared name stays "
               "nil. Not reported when the name may be built at runtime (`_G[name .. \"DB\"]`, "
               "`AceDB:New(addonName .. \"DB\")`), or when the addon shares code with sibling addons through "
               "`..\\Other\\` TOC/XML paths.",
        "bad": {"files": {"TOC": toc(*STD, "SavedVariables: FixtureDB"),
                          "core.lua": "Fixture_DB = Fixture_DB or {}\n"}},
        "good": {"files": {"TOC": toc(*STD, "SavedVariables: FixtureDB", "SavedVariablesPerCharacter: FixtureCharDB"),
                           "core.lua": "local addonName = ...\nFixtureDB = FixtureDB or {}\n"
                                       "local char = LibStub(\"AceDB-3.0\"):New(addonName .. \"CharDB\")\n"
                                       "print(char)\n"}},
        "bad_doc": "## SavedVariables: FixtureDB\n\n-- core.lua\nFixture_DB = Fixture_DB or {}",
        "good_doc": "## SavedVariables: FixtureDB\n\n-- core.lua\nFixtureDB = FixtureDB or {}",
        "lang": "lua", "refs": [SV_REF],
    },
    {
        "id": "TOC008", "category": "toc", "title": "Database-like global is not declared in SavedVariables",
        "why": "`MyAddonDB = MyAddonDB or {}` (or `if not MyAddonDB then MyAddonDB = {} end`) is the SavedVariables "
               "initialisation idiom. If the name is not declared in the TOC, the table is rebuilt from scratch on "
               "every login and the user's settings never persist. Only names that look like a database "
               "(`...DB`, `...Settings`, `...SavedVars`, `...Prefs`) initialised with that idiom are reported.",
        "bad": {"files": {"core.lua": "FixtureDB = FixtureDB or { scale = 1 }\n"}},
        "good": {"files": {"TOC": toc(*STD, "SavedVariables: FixtureDB"),
                           "core.lua": "FixtureDB = FixtureDB or { scale = 1 }\n"}},
        "bad_doc": "-- no ## SavedVariables line\nFixtureDB = FixtureDB or { scale = 1 }",
        "good_doc": "## SavedVariables: FixtureDB\n\n-- core.lua\nFixtureDB = FixtureDB or { scale = 1 }",
        "lang": "lua", "refs": [SV_REF],
    },
    {
        "id": "TOC009", "category": "toc", "title": "Invalid AllowLoadGameType / ExcludeLoadGameType",
        "why": "Valid game types are `standard`, `mainline`, `forever`/`camelot`, `classic`, `vanilla`, `tbc`, "
               "`wrath`, `cata`, `mists`, `plunderstorm`, `wowhack`. The client ignores unknown values, and if "
               "*none* is recognised the restriction is dropped entirely -- `retail` silently means 'load "
               "everywhere'. A type that is both allowed and excluded (directly or via its family) never loads.",
        "bad": {"files": {"TOC": toc(*STD, "AllowLoadGameType: retail, forever"), "core.lua": CORE}},
        "good": {"files": {"TOC": toc(*STD, "AllowLoadGameType: forever, standard",
                                      "ExcludeLoadGameType: classic"), "core.lua": CORE}},
        "bad_doc": "## AllowLoadGameType: retail, forever",
        "good_doc": "## AllowLoadGameType: forever, standard\n## ExcludeLoadGameType: classic",
        "lang": "ini", "refs": [WIKI_REF],
    },
    {
        "id": "TOC010", "category": "toc", "title": "TOC line longer than 1024 characters",
        "why": "The client reads only the first 1024 characters of each TOC line. A long `## Notes`, a long "
               "`## SavedVariables` list or a deep file path is cut off without any error.",
        "bad": {"files": {"TOC": toc("Interface: 16001, 120107", "Title: Fixture", "Notes: " + "x" * 1100,
                                     "Version: 1.0"), "core.lua": CORE}},
        "good": {"files": {"core.lua": CORE}},
        "bad_doc": "## Notes: <1100 characters of text>",
        "good_doc": "## Notes: One short sentence about the addon.",
        "lang": "ini", "refs": [TOC_REF],
    },
    {
        "id": "TOC011", "category": "toc", "title": "Missing recommended TOC metadata",
        "why": "`## Title` is the name in the AddOns list, `## Notes` its tooltip, and `## Version` what users "
               "quote in bug reports (use `@project-version@` to let the packager stamp the git tag). Each "
               "per-client TOC is read on its own, so each needs them. Localised variants (`Title-deDE`) count.",
        "bad": {"files": {"TOC": toc("Interface: 16001, 120107", "Title: Fixture"), "core.lua": CORE}},
        "good": {"files": {"core.lua": CORE}},
        "bad_doc": "## Interface: 16001, 120107\n## Title: Fixture",
        "good_doc": "## Interface: 16001, 120107\n## Title: Fixture\n## Notes: What it does.\n## Version: @project-version@",
        "lang": "ini", "refs": [TOC_REF],
    },
    {
        "id": "TOC012", "category": "toc", "title": "No addon list icon or category",
        "why": "Since 11.1 the AddOns list and addon compartment show `## IconTexture` / `## IconAtlas` and group "
               "by `## Category`. Optional, but it makes the addon easy to find. Checked on the primary TOC only.",
        "bad": {"files": {"core.lua": CORE}},
        "good": {"files": {"TOC": toc(*STD, "IconTexture: Interface\\Icons\\INV_Misc_QuestionMark",
                                      "Category: Utility"), "core.lua": CORE}},
        "bad_doc": "## Title: Fixture\n## Notes: auditor fixture",
        "good_doc": "## Title: Fixture\n## IconTexture: Interface\\Icons\\INV_Misc_QuestionMark\n## Category: Utility",
        "lang": "ini", "refs": [TOC_REF],
    },
    {
        "id": "TOC013", "category": "toc", "title": "Addon depends on itself",
        "why": "An addon listed in its own `## Dependencies`, `## OptionalDeps` or `## LoadWith` forms a "
               "dependency loop, and the client refuses to load it.",
        "bad": {"addon": "MyAddon", "files": {"TOC": toc(*STD, "Dependencies: Ace3, MyAddon"), "core.lua": CORE}},
        "good": {"addon": "MyAddon", "files": {"TOC": toc(*STD, "OptionalDeps: Ace3"), "core.lua": CORE}},
        "bad_doc": "# MyAddon/MyAddon.toc\n## Dependencies: Ace3, MyAddon",
        "good_doc": "# MyAddon/MyAddon.toc\n## OptionalDeps: Ace3",
        "lang": "ini", "refs": [TOC_REF],
    },
    # ------------------------------------------------------------------ packaging
    {
        "id": "PKG001", "category": "packaging", "title": ".pkgmeta is malformed or packages under the wrong name",
        "why": "The BigWigs / CurseForge packager names the zip's top folder after `package-as`. If that differs "
               "from the TOC name, the installed folder and its TOC no longer match and WoW ignores the addon. "
               "YAML also forbids tab indentation; a tab makes the release build fail.",
        "bad": {"addon": "MyAddon", "files": {"core.lua": CORE, ".pkgmeta": "package-as: MyAddOn\n"}},
        "good": {"addon": "MyAddon", "files": {"core.lua": CORE, ".pkgmeta": "package-as: MyAddon\n\nignore:\n  - docs\n"}},
        "bad_doc": "# MyAddon/.pkgmeta\npackage-as: MyAddOn",
        "good_doc": "# MyAddon/.pkgmeta\npackage-as: MyAddon\n\nignore:\n  - docs",
        "lang": "yaml", "refs": [PKG_REF, "First Timers `05-libraries/packager/README.md`"],
    },
    {
        "id": "PKG002", "category": "packaging", "title": "Development or junk files would ship",
        "why": "Without an `ignore:` entry, art sources (`.psd`, `.blend`), archives, `node_modules`, OS metadata "
               "(`.DS_Store`, `Thumbs.db`) and test suites end up in every user's AddOns folder. The packager "
               "always drops dot-files, so editor folders like `.vscode` are only reported for addons zipped by "
               "hand (no `.pkgmeta` and no git checkout). Test folders without any `.pkgmeta` are reported as "
               "info/low, since a custom deploy script may strip them.",
        "bad": {"files": {"core.lua": CORE, "Art/logo.psd": "psd", ".pkgmeta": "package-as: bad\n"}},
        "good": {"files": {"core.lua": CORE, "Art/logo.psd": "psd",
                           ".pkgmeta": "package-as: good\n\nignore:\n  - \"*.psd\"\n"}},
        "bad_doc": "package-as: MyAddon\n# Art/logo.psd ships",
        "good_doc": "package-as: MyAddon\nignore:\n  - \"*.psd\"\n  - tests",
        "lang": "yaml", "refs": [PKG_REF],
    },
    {
        "id": "PKG003", "category": "packaging", "title": "Missing LICENSE or CHANGELOG",
        "why": "Without a license nobody knows whether they may fork, fix or redistribute the addon. Without a "
               "changelog users cannot tell what an update changed (CurseForge/Wago show `manual-changelog`).",
        "bad": {"files": {"core.lua": CORE}},
        "good": {"files": {"core.lua": CORE, "LICENSE": "MIT License\n", "CHANGELOG.md": "# Changelog\n"}},
        "bad_doc": "MyAddon/\n  MyAddon.toc\n  core.lua",
        "good_doc": "MyAddon/\n  MyAddon.toc\n  core.lua\n  LICENSE\n  CHANGELOG.md",
        "lang": "text", "refs": [PKG_REF],
    },
    {
        "id": "PKG004", "category": "packaging", "title": "Release package is unusually large",
        "why": "Counts every file the packager would ship (dot-paths and `.pkgmeta` ignores excluded) against "
               "`thresholds.package_size_mb_warn` (default 20 MB). Huge packages are almost always docs, videos "
               "or uncompressed source art shipping by accident.",
        "bad": {"files": {"core.lua": CORE + ("-- padding\n" * 40),
                          ".addon-auditor.toml": "[thresholds]\npackage_size_mb_warn = 0.0001\n"}},
        "good": {"files": {"core.lua": CORE}},
        "bad_doc": "Shipped files total 48.3 MB (docs/ and Art/*.psd not ignored)",
        "good_doc": "ignore:\n  - docs\n  - \"*.psd\"",
        "lang": "yaml", "refs": [PKG_REF],
    },
    {
        "id": "PKG005", "category": "packaging", "title": "Vendored library without a version marker",
        "why": "LibStub libraries carry a MINOR version so the newest embedded copy wins. A library folder with "
               "no `NewLibrary(MAJOR, MINOR)`, no `## Version` and no `.pkgmeta` external cannot be updated "
               "safely and may clobber other addons' copies. Low confidence: some small helpers are fine as-is.",
        "bad": {"files": {"TOC": toc(*STD, files="Libs\\LibFoo\\LibFoo.lua\ncore.lua"), "core.lua": CORE,
                          "Libs/LibFoo/LibFoo.lua": "LibFoo = {}\nfunction LibFoo.Hello() return 1 end\n"}},
        "good": {"files": {"TOC": toc(*STD, files="Libs\\LibFoo\\LibFoo.lua\ncore.lua"), "core.lua": CORE,
                           "Libs/LibFoo/LibFoo.lua": "local MAJOR, MINOR = \"LibFoo-1.0\", 3\n"
                                                     "local lib = LibStub:NewLibrary(MAJOR, MINOR)\n"
                                                     "if not lib then return end\n"}},
        "bad_doc": "-- Libs/LibFoo/LibFoo.lua\nLibFoo = {}",
        "good_doc": "-- Libs/LibFoo/LibFoo.lua\nlocal MAJOR, MINOR = \"LibFoo-1.0\", 3\n"
                    "local lib = LibStub:NewLibrary(MAJOR, MINOR)\nif not lib then return end",
        "lang": "lua", "refs": [PKG_REF, "First Timers `06-notes/addon-dev/ace3-and-libraries.md`"],
    },
]


def write_side(folder: Path, side: dict) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    files = dict(side.get("files", {}))
    addon = side.get("addon")
    root = folder / addon if addon else folder
    root.mkdir(parents=True, exist_ok=True)
    toc_name = side.get("toc_name") or f"{root.name}.toc"
    (root / toc_name).write_text(files.pop("TOC", DEFAULT_TOC), encoding="utf-8")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def main() -> int:
    force = "--force" in sys.argv
    for s in SPECS:
        base = ROOT / "tests" / "fixtures" / s["category"] / s["id"]
        if base.exists() and not force:
            print(f"skip {s['id']} (exists)")
            continue
        write_side(base / "bad", s["bad"])
        write_side(base / "good", s["good"])
        lang = s.get("lang", "ini")
        refs = "\n".join(f"- {r}" for r in s.get("refs", []))
        doc = (f"# {s['id']}: {s['title']}\n\n**Category:** {s['category']}\n\n## Why\n\n{s['why'].strip()}\n\n"
               f"## Bad\n\n```{lang}\n{s['bad_doc'].strip()}\n```\n\n## Good\n\n```{lang}\n{s['good_doc'].strip()}\n```\n\n"
               f"## References\n\n{refs}\n")
        (ROOT / "rules-docs" / f"{s['id']}.md").write_text(doc, encoding="utf-8")
        print(f"wrote {s['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
