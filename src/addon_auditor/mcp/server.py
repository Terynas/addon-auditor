"""MCP server (stdio). Run ``addon-auditor-mcp`` or ``python -m addon_auditor.mcp.server``."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .. import __version__
from . import tools

INSTRUCTIONS = (
    "Deterministic World of Warcraft addon auditor (luacheck, TOC, API existence per client, performance, "
    "taint/security, SavedVariables, usability, packaging, runtime probe data). Workflow: memory_hints -> "
    "recall from your memory service; audit_changes after each edit batch; fix errors, then perf, then ux; "
    "explain_rule when unsure; audit_addon before finishing (gate must pass); record_learning for false "
    "positives; store memory_hints lessons when ingest_recommended is true. Suppress only with a real reason."
)


def _server() -> Any:
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer("addon-auditor", version=__version__, instructions=INSTRUCTIONS)
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # type: ignore[attr-defined]  # mcp < 2

        return FastMCP("addon-auditor", instructions=INSTRUCTIONS)


def _wrap(fn: Callable[..., Any]) -> Callable[..., str]:
    def call(*args: Any, **kwargs: Any) -> str:
        try:
            return json.dumps(fn(*args, **kwargs), indent=1, ensure_ascii=False, default=str)
        except (tools.ToolError, ValueError, OSError, NotImplementedError) as exc:
            return json.dumps({"error": str(exc)})

    call.__name__ = fn.__name__
    call.__doc__ = fn.__doc__
    call.__annotations__ = {**fn.__annotations__, "return": str}
    return call


mcp = _server()


@mcp.tool(description=(
    "Full audit of a WoW addon folder (or any file inside it). Returns gate pass/fail, per-category scores and "
    "ranked findings (rule_id, severity, confidence, file, line, message, fix_hint). Optional filters: profiles "
    "(forever, classic-era, classic, mainline), categories (lint, toc, api, perf, security, savedvars, ux, "
    "packaging, runtime), min_severity (info|warn|error), rule_ids; probe_path = AuditorProbe SavedVariables."))
def audit_addon(path: str, profiles: list[str] | None = None, categories: list[str] | None = None,
                min_severity: str | None = None, rule_ids: list[str] | None = None,
                probe_path: str | None = None, max_findings: int = tools.DEFAULT_MAX_FINDINGS) -> str:
    return _wrap(tools.audit_addon)(path, profiles, categories, min_severity, rule_ids, probe_path, max_findings)


@mcp.tool(description=(
    "Fast diff audit: only findings on lines changed vs git_ref (default HEAD, includes untracked files) or in "
    "the listed files (paths relative to the addon root). Use after every edit batch."))
def audit_changes(path: str, files: list[str] | None = None, git_ref: str = "HEAD",
                  min_severity: str | None = None, max_findings: int = tools.DEFAULT_MAX_FINDINGS) -> str:
    return _wrap(tools.audit_changes)(path, files, git_ref, min_severity, max_findings)


@mcp.tool(description="Rationale, bad/good examples and references for a rule id (e.g. PERF001).")
def explain_rule(rule_id: str) -> str:
    return _wrap(tools.explain_rule)(rule_id)


@mcp.tool(description="List rules (optionally one category) with id, severity, title and client profiles.")
def list_rules(category: str | None = None) -> str:
    return _wrap(tools.list_rules)(category)


@mcp.tool(description="Parsed TOC(s), detected client profiles, load order, and TOC/packaging findings.")
def check_toc(path: str) -> str:
    return _wrap(tools.check_toc)(path)


@mcp.tool(description=(
    "Does an API symbol exist per client? Accepts Name, C_Namespace.Name. Returns per-profile existence and "
    "deprecation. Use before calling any API you are not certain about."))
def check_api(symbol: str, profiles: list[str] | None = None) -> str:
    return _wrap(tools.check_api)(symbol, profiles)


@mcp.tool(description=(
    "Summarise AuditorProbe runtime data (WTF/Account/<acct>/SavedVariables/AuditorProbe.lua): memory growth, "
    "CPU ms/s and event hotspots per addon."))
def ingest_probe(savedvariables_path: str, addon: str | None = None) -> str:
    return _wrap(tools.ingest_probe)(savedvariables_path, addon)


@mcp.tool(description=(
    "Insert an inline `-- auditor:ignore RULE reason` above file:line. Only for deliberate trade-offs; the "
    "reason is mandatory and should explain why the finding does not apply."))
def suppress_finding(path: str, rule_id: str, file: str, line: int, reason: str) -> str:
    return _wrap(tools.suppress_finding)(path, rule_id, file, line, reason)


@mcp.tool(description=(
    "Accept all current findings into .addon-auditor/baseline.json so later audits only show new ones. "
    "Use once when adopting the auditor on a legacy addon, not to hide new problems."))
def update_baseline(path: str) -> str:
    return _wrap(tools.update_baseline)(path)


@mcp.tool(description=(
    "Record a verdict about a finding in .addon-auditor/learnings.jsonl. verdict: false_positive (future "
    "matching findings are downgraded to info), accepted, fixed, pattern. Never include secrets in note."))
def record_learning(path: str, rule_id: str, verdict: str, note: str, file: str | None = None,
                    snippet: str | None = None) -> str:
    return _wrap(tools.record_learning)(path, rule_id, verdict, note, file, snippet)


@mcp.tool(description=(
    "Memory loop: suggested search queries to recall prior audit decisions for this addon, and an ingest-ready "
    "lessons document (ingest_recommended) built from recurring findings, learnings and suppressions. Pass a "
    "previous audit report to avoid re-running the audit."))
def memory_hints(path: str, report: dict[str, Any] | None = None) -> str:
    return _wrap(tools.memory_hints)(path, report)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
