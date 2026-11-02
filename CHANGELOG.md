# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added

- Initial release of **addon-auditor**: a deterministic auditor for World of Warcraft addons built for AI coding agents. Supports WoW Forever, Classic Era, Classic and Mainline / Midnight, detected from TOC `## Interface`, per-client TOC suffixes and `AllowLoadGameType`.
- Engine: built-in Lua 5.1 parser and scope resolver, TOC parser, ranked findings with severity, confidence and fix hints, per-category scores and a pass/fail gate, diff mode (git ref or file list), baselines, inline suppressions with mandatory reasons, and `.addon-auditor.toml` configuration.
- Reports in Markdown, JSON and SARIF 2.1.0.
- README banner and badges (`.github/banner.jpg`) matching the Terynas addon repos.
- CLI `addon-auditor` with these commands: `audit`, `diff`, `explain`, `rules`, `api`, `baseline`, `learn`, `luacheckrc` (writes a compact per-addon `.luacheckrc`), `memory-hints` and `probe-ingest`.
- Rule packs, 87 rules in all, each with a documentation page and good/bad fixtures:
  - **LINT001–LINT009**: luacheck integration, with a built-in accidental-global check when luacheck is not installed.
  - **TOC001–TOC013**: TOC checks.
  - **API001–API009**: per-client API existence, deprecations and Forever restrictions.
  - **PERF001–PERF013**: OnUpdate, hot-path allocation, frame churn, timers, events and SavedVariables growth.
  - **SEC001–SEC009**: taint, combat lockdown, `loadstring`, global hygiene and chat or addon-message safety.
  - **SV001–SV006**: SavedVariables checks.
  - **UX001–UX016**: Esc-to-close, clamping, saved positions, slash help, options, login spam, `BackdropTemplate`, tooltips, Forever `UICheckButtonTemplate`.
  - **PKG001–PKG005**: packaging.
  - **RUN001–RUN006**: runtime data.
  - **META001**: suppressions without a reason.
- MCP server `addon-auditor-mcp` with 11 tools (`audit_addon`, `audit_changes`, `explain_rule`, `list_rules`, `check_toc`, `check_api`, `ingest_probe`, `suppress_finding`, `update_baseline`, `record_learning`, `memory_hints`). `ADDON_AUDITOR_ROOTS` restricts which paths it may use.
- Agent skill `skills/addon-auditor/SKILL.md`, a Cursor plugin manifest and `scripts/install-cursor-plugin.sh`.
- **AuditorProbe** in-game companion addon (`/probe start|stop|report|reset`). It samples per-addon memory, CPU through the AddOn profiler or `scriptProfile`, and event deliveries for the RUNTIME rules.
- Memory loop: `memory_hints` returns recall queries and an ingest-ready lessons document, and `learnings.jsonl` verdicts downgrade known false positives.
- Bundled API name data for Forever and Mainline, rebuilt with `scripts/build_api_data.py`.
- GitHub Actions CI: ruff, mypy, pytest with luacheck through hererocks, and a self-audit of AuditorProbe.
