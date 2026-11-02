---
name: addon-auditor
description: >-
  Audit World of Warcraft addons while coding: luacheck, TOC, API existence per client (Forever,
  Classic Era, Mainline), performance, taint/security, SavedVariables, usability, packaging and
  in-game runtime data. Use whenever you create or edit addon .lua/.toc/.xml files, before saying
  addon work is done, before packaging or publishing, when reviewing AI-written addon code, or
  when the user mentions performance, lag, memory, taint, ADDON_ACTION_BLOCKED, or an addon audit.
---

# addon-auditor

Deterministic auditor for WoW addons. It returns ranked findings with a `fix_hint` and a rule ID
you can look up. It never calls an LLM; you triage and fix.

Interfaces (prefer the first available):

1. **MCP** server `addon-auditor`: `audit_changes`, `audit_addon`, `explain_rule`, `check_api`,
   `check_toc`, `list_rules`, `ingest_probe`, `suppress_finding`, `update_baseline`,
   `record_learning`, `memory_hints`.
2. **CLI**: `addon-auditor audit|diff|explain|rules|api|baseline|learn|luacheckrc|probe-ingest|memory-hints`
   (exit code 1 when the gate fails; `--format json` for machine output).

## Workflow (every addon coding task)

1. **Recall.** Call `memory_hints(path)`. If you have a memory service (e.g. Hindsight
   `hindsight_search_knowledge_pages`), run its `search_queries` and honour earlier decisions:
   known false positives, accepted trade-offs, thresholds.
2. **Check before you call.** Unsure an API exists on the target client? `check_api("C_Foo.Bar")`
   first. Never invent APIs; the auditor will flag them as errors (API pack).
3. **Audit each edit batch.** `audit_changes(path)` (git diff vs `HEAD`, includes untracked files)
   or `audit_changes(path, files=[...])` outside git. It only reports lines you touched.
4. **Fix in order:** `error` → `perf` → `security` → `ux` → the rest. Within a severity, high
   confidence first. Use `explain_rule(ID)` whenever the reason or fix is not obvious.
5. **Gate.** Before declaring the work done, run `audit_addon(path)`. `gate` must be `pass`.
   Report one line: `addon-auditor: pass (score 94/100, 0 errors, 3 warn)`.
6. **Remember.** For a finding that is wrong, call `record_learning(path, ID, "false_positive", why)`.
   Then call `memory_hints(path, report)`; when `ingest_recommended` is true and you have a memory
   service, store `lessons_markdown` under `document_title` (Hindsight: `hindsight_ingest_document`).
   Never put secrets, tokens or account names into notes or memory.

## Rules of engagement

- Do not silence findings to pass the gate. Suppress (`suppress_finding` / `-- auditor:ignore ID reason`)
  only for a deliberate, explained trade-off; reasonless suppressions are reported as META001.
- `update_baseline` is for adopting the auditor on a legacy addon, once, with the user's consent.
- Low-confidence findings are hints. Verify against the code before changing behaviour.
- `info` findings in `lint` with "no bundled API data for classic-era" mean the auditor cannot
  verify that client; check the API another way instead of deleting the call.
- Runtime numbers (memory growth, CPU ms/s, event hotspots) need the **AuditorProbe** addon:
  install `probe/AuditorProbe` into `Interface/AddOns`, `/probe start`, play normally, `/probe stop`,
  `/reload`, then `ingest_probe(".../WTF/Account/<ACCOUNT>/SavedVariables/AuditorProbe.lua")`, or
  pass it as `probe_path` to `audit_addon` to get RUNTIME findings.

## Categories

| Category | Looks for |
|----------|-----------|
| lint | luacheck: syntax, undefined/accidental globals, shadowing, unused, dead code |
| toc | TOC naming, Interface per client, missing/unlisted files, SavedVariables, metadata |
| api | APIs missing or deprecated on a targeted client, Forever-specific restrictions |
| perf | unthrottled OnUpdate, allocation in hot paths, frame churn, timers, event misuse |
| security | taint (replacing Blizzard functions/scripts), combat-lockdown, loadstring, global hygiene |
| savedvars | SavedVariables init timing, storing functions/frames, data loss |
| ux | Esc-to-close, clamping, saved positions, slash help, options panel, login spam |
| packaging | shipped junk, `.pkgmeta`, size, LICENSE/CHANGELOG |
| runtime | probe data over thresholds |

Configuration lives in `<addon>/.addon-auditor.toml` (profiles, excludes, per-rule severity,
thresholds, `fail_on`). Generate a matching `.luacheckrc` with `addon-auditor luacheckrc --write`.
