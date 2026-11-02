"""Fixture/doc specs for LINT and META rules."""

LUACHECK_REF = "[luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)"

SPECS = [
    {
        "id": "LINT001", "category": "lint", "title": "Lua syntax error",
        "why": "WoW stops loading a file at the first syntax error. Everything defined after it (and often the "
               "whole addon, because later files depend on it) is missing, and the user sees a Lua error on login.",
        "bad": {"core.lua": "local x = = 1\n"},
        "good": {"core.lua": "local x = 1\nprint(x)\n"},
        "refs": [LUACHECK_REF],
    },
    {
        "id": "LINT002", "category": "lint", "title": "Access to an undefined global",
        "why": "A global that neither your addon nor the client defines evaluates to `nil`. Calling it throws "
               "`attempt to call a nil value`. Common causes: typos, a missing `local`, or an API invented by an "
               "AI assistant or removed in this client. Reads that are existence checks (`if X then`, `X or Y`) "
               "are not reported.",
        "bad": {"core.lua": "local hp = UnitHealthh(\"player\")\nprint(hp)\n"},
        "good": {"core.lua": "local hp = UnitHealth(\"player\")\nprint(hp)\n"},
        "refs": [LUACHECK_REF, "`addon-auditor api <Name>` to check a symbol per client"],
    },
    {
        "id": "LINT003", "category": "lint", "title": "Accidental global variable",
        "why": "Every addon shares one global environment. A forgotten `local` leaks state that other addons can "
               "overwrite (or that overwrites theirs), and global lookups are slower than locals. Keep exported "
               "state on one addon-prefixed namespace table and declare everything else `local`.",
        "bad": {"core.lua": "local function Count()\n  counter = (counter or 0) + 1\n  return counter\nend\nprint(Count())\n"},
        "good": {"core.lua": "local counter = 0\nlocal function Count()\n  counter = counter + 1\n  return counter\nend\nprint(Count())\n"},
        "refs": [LUACHECK_REF],
    },
    {
        "id": "LINT004", "category": "lint", "title": "Overwriting a read-only (Blizzard) global",
        "why": "Replacing a client function (`GetItemInfo = ...`, `function ChatFrame_OnHyperlinkShow() ... end`) "
               "changes it for every addon and the default UI, and the replacement taints secure code paths that "
               "call it, which leads to `ADDON_ACTION_BLOCKED`. Post-hook it instead.",
        "bad": {"core.lua": "function GetItemInfo(item)\n  return nil\nend\n"},
        "good": {"core.lua": "hooksecurefunc(\"GetItemInfo\", function(item)\n  -- runs after the original\nend)\n"},
        "refs": [LUACHECK_REF, "Warcraft Wiki: hooksecurefunc"],
    },
    {
        "id": "LINT005", "category": "lint", "title": "Unused variable / value",
        "why": "Unused locals and values are dead code or a sign the wrong variable is used further down.",
        "bad": {"core.lua": "local function F()\n  local unused = 1\n  return 2\nend\nprint(F())\n"},
        "good": {"core.lua": "local function F()\n  return 2\nend\nprint(F())\n"},
        "refs": [LUACHECK_REF],
    },
    {
        "id": "LINT006", "category": "lint", "title": "Shadowed variable",
        "why": "A local that shadows an outer local makes later edits silently touch the wrong variable.",
        "bad": {"core.lua": "local count = 1\nlocal function F()\n  local count = 2\n  return count\nend\nprint(count, F())\n"},
        "good": {"core.lua": "local count = 1\nlocal function F()\n  local inner = 2\n  return inner\nend\nprint(count, F())\n"},
        "refs": [LUACHECK_REF],
    },
    {
        "id": "LINT007", "category": "lint", "title": "Suspicious control flow",
        "why": "Unreachable code, loops that always exit on the first pass and empty branches usually mean a "
               "condition or `return` is in the wrong place.",
        "bad": {"core.lua": "local function F(t)\n  for _, v in ipairs(t) do\n    return v\n  end\nend\nprint(F({}))\n"},
        "good": {"core.lua": "local function F(t)\n  return t[1]\nend\nprint(F({}))\n"},
        "refs": [LUACHECK_REF],
    },
    {
        "id": "LINT008", "category": "lint", "title": "Style / formatting",
        "why": "Trailing whitespace and inconsistent indentation are noise in diffs. Low priority; fix while "
               "touching the line.",
        "bad": {"core.lua": "local x = 1   \nprint(x)\n"},
        "good": {"core.lua": "local x = 1\nprint(x)\n"},
        "refs": [LUACHECK_REF],
    },
    {
        "id": "LINT009", "category": "lint", "title": ".luacheckrc disables global checks",
        "why": "Accidental globals and calls to APIs that do not exist are the most valuable things luacheck "
               "finds in WoW code. `global = false`, `allow_defined = true` or ignoring the `11x` codes turns "
               "that off for the whole addon. List the globals you really export in `globals = { ... }`.",
        "bad": {"core.lua": "local x = 1\nprint(x)\n", ".luacheckrc": "std = \"lua51\"\nglobal = false\n"},
        "good": {"core.lua": "local x = 1\nprint(x)\n", ".luacheckrc": "std = \"lua51\"\nglobals = { \"MyAddonDB\" }\n"},
        "bad_doc": "-- .luacheckrc\nstd = \"lua51\"\nglobal = false",
        "good_doc": "-- .luacheckrc\nstd = \"lua51\"\nglobals = { \"MyAddonDB\", \"SLASH_MYADDON1\" }",
        "refs": ["[luacheck config](https://luacheck.readthedocs.io/en/stable/config.html)"],
    },
    {
        "id": "META001", "category": "meta", "title": "Suppression without a reason",
        "why": "An `-- auditor:ignore ID` comment hides a finding from every future audit. Without a reason the "
               "next agent cannot tell whether it was a deliberate trade-off or a shortcut, and may copy the "
               "pattern elsewhere.",
        "bad": {"core.lua": "-- auditor:ignore PERF001\nlocal x = 1\nprint(x)\n"},
        "good": {"core.lua": "-- auditor:ignore PERF001 throttled to 0.2s by the caller\nlocal x = 1\nprint(x)\n"},
    },
]
