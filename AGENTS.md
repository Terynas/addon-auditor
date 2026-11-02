# Agent instructions (addon-auditor)

Tool-agnostic contract for Claude Code, GitHub Copilot, Cursor, Codex, Gemini, Windsurf, and similar agents. This file covers two audiences:

1. **Agents working on this repo** (the auditor itself).
2. **Agents using the auditor** while writing WoW addons — see [`skills/addon-auditor/SKILL.md`](skills/addon-auditor/SKILL.md).

Never push. Never add `Co-authored-by` / `Generated-by` trailers. The maintainer pushes and merges manually.

## Product

Deterministic analysis engine for World of Warcraft addons (WoW Forever `16001`, Classic Era `11509`, Mainline / Midnight `12xxxx`). No LLM calls inside; agents call it through the CLI or the MCP server and act on the structured findings.

## Layout

| Path | What |
|------|------|
| `src/addon_auditor/core/` | addon discovery, TOC parser, Lua 5.1 lexer/parser (`lua_ast.py`), findings, config, suppressions, baseline, scoring |
| `src/addon_auditor/adapters/` | luacheck runner/parser, API index (Forever dump + Mainline/Era annotations) |
| `src/addon_auditor/rules/` | rule packs: `lint`, `toc`, `api`, `perf`, `security`, `savedvars`, `ux`, `packaging`, `runtime` |
| `src/addon_auditor/reporters/` | JSON, SARIF 2.1.0, Markdown |
| `src/addon_auditor/mcp/server.py` | MCP server (`addon-auditor-mcp`) |
| `rules-docs/<ID>.md` | one page per rule: why, bad, good, references |
| `probe/AuditorProbe/` | in-game companion addon for runtime CPU/memory/event sampling |
| `tests/fixtures/<pack>/<ID>/{bad,good}/` | fixtures every rule must have |

## Must (when changing this repo)

- Every new rule: unique ID, entry in its pack's `RULES`, `rules-docs/<ID>.md`, a `bad` fixture that fires and a `good` fixture that does not. `pytest` enforces this.
- Prefer AST-based checks (`core/lua_ast.py`); regex fallbacks must set `confidence="low"`.
- False positives are worse than misses: an agent will "fix" whatever we report. Default to `warn`/`info` unless the pattern is unambiguously a bug.
- Rule messages are imperative and specific (what to change), `fix_hint` contains a short corrected snippet where possible.
- Run `ruff check`, `mypy`, `pytest` before finishing.
- Update `CHANGELOG.md` under `[Unreleased]` for user-facing changes (new rules, changed severities, new tools).

## Memory

This repo uses Hindsight for durable decisions (rule thresholds, resolved conflicts like `UICheckButtonTemplate`). Search it before changing a rule's severity or threshold; ingest the decision after.
