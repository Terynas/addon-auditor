<p align="center">
  <img src=".github/banner.jpg" alt="Addon Auditor — catch it before players do" width="100%">
</p>

<p align="center">
  <b>A WoW addon auditor that AI coding agents call while they write code.</b><br>
  Performance, usability, luacheck, TOC, API, taint and runtime checks — over a CLI or MCP, with no LLM keys.
</p>

<p align="center">
  <a href="https://github.com/Terynas/addon-auditor/actions/workflows/ci.yml"><img src="https://github.com/Terynas/addon-auditor/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/WoW-Forever%20%7C%20Classic%20Era%20%7C%20Midnight-d6a64a?style=flat-square" alt="WoW Forever, Classic Era and Midnight">
  <img src="https://img.shields.io/badge/rules-87-d6a64a?style=flat-square" alt="87 rules">
  <img src="https://img.shields.io/badge/python-3.11%2B-2c2d72?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/MCP-server-2c2d72?style=flat-square" alt="MCP server">
  <img src="https://img.shields.io/badge/license-MIT-6b6b6b?style=flat-square" alt="MIT license">
</p>

---

# addon-auditor

A deterministic auditor for World of Warcraft addons, built to be called by AI coding agents while they write code (and by humans and CI).

It focuses on **performance** and **usability**, and also covers luacheck, the TOC, API existence per client, taint and security, SavedVariables, packaging, and runtime data from an in-game probe. Findings come back ranked, with a rule ID, a confidence level, a `fix_hint`, and a documentation page for each rule. The tool makes no LLM calls and needs no API keys; the agent does the triage and fixing.

Supported clients: **WoW Forever** (`16xxx`), **Classic Era** (`11xxx`), **Classic** progression, and **Mainline / Midnight** (`11xxxx`–`12xxxx`). These are detected from `## Interface` lines, per-client TOC files (`_Mainline.toc`, `_Vanilla.toc`, …), and `AllowLoadGameType`.

## Install

```bash
pip install "addon-auditor[mcp]"        # or: uv tool install "addon-auditor[mcp]"
luarocks install luacheck               # optional, enables the LINT pack
```

From a checkout: `uv venv && uv pip install -e ".[dev,mcp]"`.

If luacheck is not on `PATH`, set `ADDON_AUDITOR_LUACHECK=/path/to/luacheck`.

## Use it from the command line

```bash
addon-auditor audit MyAddon                      # full audit, Markdown report, exit 1 if the gate fails
addon-auditor diff MyAddon                       # only lines changed vs HEAD (plus untracked files)
addon-auditor audit MyAddon --format sarif -o audit.sarif
addon-auditor audit MyAddon --category perf --category ux --min-severity warn
addon-auditor explain PERF001                    # why, bad/good example, references
addon-auditor rules                              # every rule with severity and client scope
addon-auditor api C_Container.GetContainerItemInfo   # does it exist on each client?
addon-auditor luacheckrc MyAddon --write         # compact .luacheckrc tailored to the addon
addon-auditor baseline MyAddon                   # accept current findings once (legacy adoption)
addon-auditor learn MyAddon UX004 false_positive "HUD frame is re-anchored to the screen on every login"
```

Example output:

```text
# addon-auditor: MyAddon
**Gate:** FAIL (fails on `error`) · **Score:** 71/100 · **Profiles:** forever, mainline
- **ERROR** `API001` core.lua:41 — `C_Container.GetItemInfoz` does not exist on forever, mainline
- **WARN** `PERF001` ui.lua:88 — OnUpdate handler runs every frame without a throttle
  - fix: self.t = (self.t or 0) + elapsed; if self.t < 0.1 then return end; self.t = 0
```

## Use it from an agent (MCP)

Run `addon-auditor-mcp` (stdio). Tools:

| Tool | Purpose |
|------|---------|
| `audit_changes` | Fast diff audit after each edit batch (git ref or explicit files) |
| `audit_addon` | Full audit with gate and scores; optional `probe_path` for runtime rules |
| `explain_rule`, `list_rules` | Rule rationale and catalogue |
| `check_api`, `check_toc` | Per-client API existence; parsed TOC, profiles and load order |
| `ingest_probe` | Summarise AuditorProbe runtime data |
| `suppress_finding`, `update_baseline` | Reasoned inline suppression; legacy baseline |
| `record_learning`, `memory_hints` | Learning loop (see below) |

Set `ADDON_AUDITOR_ROOTS` (paths separated by `:`) to limit the folders the server may read and write.

**Cursor:** `scripts/install-cursor-plugin.sh` installs the MCP server and the agent skill as a local plugin. `--dev` makes the plugin follow your checkout.

**Other agents:** point your MCP config at `addon-auditor-mcp`. Then give the agent [`skills/addon-auditor/SKILL.md`](skills/addon-auditor/SKILL.md), which describes the workflow: recall, audit changes, fix by severity, gate, remember.

## Rule packs

| Category | Examples |
|----------|----------|
| `lint` | luacheck syntax errors, undefined or accidental globals, overwriting Blizzard globals, shadowing; `.luacheckrc` files that turn global checks off |
| `toc` | TOC name vs folder, Interface per client, missing or unlisted files, SavedVariables declared vs used, game-type sanity, 1024-character lines |
| `api` | APIs that are hallucinated or missing on a targeted client, deprecated APIs, Forever-specific restrictions |
| `perf` | unthrottled `OnUpdate`, allocation in hot paths, frame churn, timers that are never cancelled, `RegisterUnitEvent` opportunities, unbounded SavedVariables growth |
| `security` | taint from replacing Blizzard functions or scripts, combat lockdown, `loadstring` on external data, global namespace hygiene, chat spam |
| `savedvars` | SavedVariables initialised before they load, functions or frames stored in SavedVariables, wholesale resets |
| `ux` | Esc to close, clamping, saved positions, slash command help, options panel, login spam, `BackdropTemplate`, tooltips |
| `packaging` | dev files that would ship, `.pkgmeta`, size, LICENSE and CHANGELOG |
| `runtime` | memory size and growth, CPU ms/s, frame hitches, event storms (needs probe data) |

Every rule has a page in [`rules-docs/`](rules-docs/).

## Configuration

To configure the auditor for one addon, add `.addon-auditor.toml` to the addon folder:

```toml
profiles = ["forever", "mainline"]     # override detection
exclude = ["Generated/**"]
fail_on = "error"                       # gate threshold: error | warn | info
min_severity = "info"
disabled_categories = ["packaging"]

[rules]
UX007 = "off"
PERF008 = { severity = "warn" }

[thresholds]
runtime_cpu_ms_per_sec_warn = 0.5
```

You can also suppress inline. A suppression without a reason is itself reported, as META001.

```lua
frame:SetScript("OnUpdate", Tick) -- auditor:ignore PERF001 Tick self-throttles via its own timer
-- auditor:ignore-file UX010 developer build announces itself on purpose
```

The `.addon-auditor/` folder in each addon holds `baseline.json` (accepted legacy findings) and `learnings.jsonl` (recorded verdicts).

## Runtime data: AuditorProbe

`probe/AuditorProbe` is a small in-game addon. It records per-addon memory, CPU time, and event deliveries:

1. Copy `probe/AuditorProbe` into `Interface/AddOns/`. For CPU data, enable the AddOn profiler (Mainline and Forever), or run `/console scriptProfile 1` and `/reload`.
2. In game: `/probe start`. Play normally for a few minutes, then `/probe stop` and `/reload`.
3. Run `addon-auditor audit MyAddon --probe "<WoW>/WTF/Account/<ACCOUNT>/SavedVariables/AuditorProbe.lua"`.

The probe only post-hooks `RegisterEvent` (`hooksecurefunc`), so it does not taint secure code. Any events an addon registers before AuditorProbe loads are not counted.

## Learning loop

`memory_hints` returns search queries to run before an audit, and a lessons document to store afterwards when `ingest_recommended` is true. The lessons cover recurring findings, confirmed false positives, accepted trade-offs, and suppressions with reasons. The tool works with any memory service; the skill shows how to use it with Hindsight. With no memory service, `learnings.jsonl` still works: a `false_positive` verdict downgrades matching findings to `info` and keeps them out of the gate.

## Development

```bash
uv venv && uv pip install -e ".[dev,mcp]"
.venv/bin/ruff check src tests scripts && .venv/bin/mypy && .venv/bin/python -m pytest -q
```

Every rule needs a `rules-docs/<ID>.md` page plus `tests/fixtures/<category>/<ID>/{bad,good}/` fixtures; `pytest` enforces this. See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).

## License

MIT. See [LICENSE](LICENSE).
