"""Tool implementations shared by the MCP server (and usable directly from Python).

Every function returns JSON-serialisable data. Paths are checked against ``ADDON_AUDITOR_ROOTS``
(``os.pathsep``-separated); when unset, any local path is allowed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..core.baseline import append_learning, write_baseline
from ..core.context import AuditContext, find_addon_root
from ..core.engine import AuditOptions, audit_all_findings, git_changed_lines, load_rules, run_audit
from ..core.finding import RULES, SEVERITY_RANK
from ..core.memory import memory_hints as _memory_hints

DEFAULT_MAX_FINDINGS = 150
VERDICTS = ("false_positive", "accepted", "fixed", "pattern")
_RULE_ID = re.compile(r"^[A-Z]+\d{3}$")


class ToolError(ValueError):
    pass


def allowed_roots() -> list[Path]:
    raw = os.environ.get("ADDON_AUDITOR_ROOTS", "")
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]


def check_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    roots = allowed_roots()
    if roots and not any(p == r or r in p.parents for r in roots):
        raise ToolError(f"{p} is outside ADDON_AUDITOR_ROOTS ({', '.join(map(str, roots))})")
    if not p.exists():
        raise ToolError(f"{p} does not exist")
    return p


def _addon_root(path: str) -> Path:
    return find_addon_root(check_path(path))


def _opts(profiles: list[str] | None, categories: list[str] | None, min_severity: str | None,
          rule_ids: list[str] | None = None) -> AuditOptions:
    if min_severity and min_severity not in SEVERITY_RANK:
        raise ToolError(f"min_severity must be one of {list(SEVERITY_RANK)}")
    return AuditOptions(profiles=profiles or None, categories=categories or None,
                        rule_ids=[r.upper() for r in rule_ids] if rule_ids else None, min_severity=min_severity)


def audit_addon(path: str, profiles: list[str] | None = None, categories: list[str] | None = None,
                min_severity: str | None = None, rule_ids: list[str] | None = None,
                probe_path: str | None = None, max_findings: int = DEFAULT_MAX_FINDINGS) -> dict[str, Any]:
    load_rules()
    opts = _opts(profiles, categories, min_severity, rule_ids)
    if probe_path:
        opts.probe_path = check_path(probe_path)
    return run_audit(check_path(path), opts).to_dict(max_findings=max_findings)


def audit_changes(path: str, files: list[str] | None = None, git_ref: str = "HEAD",
                  min_severity: str | None = None, max_findings: int = DEFAULT_MAX_FINDINGS) -> dict[str, Any]:
    load_rules()
    root = _addon_root(path)
    opts = _opts(None, None, min_severity)
    if files:
        opts.changed = {f.replace("\\", "/"): None for f in files}
    else:
        if not re.match(r"^[\w./~^@{}-]+$", git_ref):
            raise ToolError("invalid git_ref")
        opts.changed = git_changed_lines(root, git_ref)
    return run_audit(root, opts).to_dict(max_findings=max_findings)


def explain_rule(rule_id: str) -> dict[str, Any]:
    from ..rules_docs import read_doc

    load_rules()
    rid = rule_id.upper()
    r = RULES.get(rid)
    if r is None:
        raise ToolError(f"unknown rule {rid}")
    m = r.meta
    return {"id": m.id, "category": m.category, "severity": m.severity, "confidence": m.confidence,
            "title": m.title, "summary": m.summary, "profiles": m.profiles, "doc": read_doc(rid)}


def list_rules(category: str | None = None) -> list[dict[str, Any]]:
    load_rules()
    return [{"id": r.meta.id, "category": r.meta.category, "severity": r.meta.severity, "title": r.meta.title,
             "profiles": r.meta.profiles}
            for r in sorted(RULES.values(), key=lambda r: r.meta.id)
            if not category or r.meta.category == category]


def check_toc(path: str) -> dict[str, Any]:
    load_rules()
    root = _addon_root(path)
    ctx = AuditContext(root)
    tocs = [{
        "file": t.path.name, "suffix": t.suffix, "interfaces": t.interfaces, "profiles": sorted(t.profiles),
        "title": t.get("Title"), "version": t.get("Version"), "saved_variables": t.saved_variables,
        "saved_variables_per_character": t.saved_variables_per_character, "dependencies": t.dependencies,
        "optional_deps": t.optional_deps, "files": [e.path for e in t.files],
    } for t in ctx.addon.tocs]
    report = run_audit(root, AuditOptions(categories=["toc", "packaging"], min_severity="info")).to_dict()
    return {"addon": ctx.addon.name, "profiles": sorted(ctx.profiles), "tocs": tocs,
            "load_order": ctx.load_order, "findings": report["findings"], "gate": report["gate"]}


def check_api(symbol: str, profiles: list[str] | None = None) -> dict[str, Any]:
    from ..adapters.api_index import ApiIndex

    if not re.match(r"^[A-Za-z_][\w.:]*$", symbol):
        raise ToolError("symbol must look like Name, C_Namespace.Name or Object:Method")
    return ApiIndex.for_profiles(set(profiles or [])).lookup(symbol)


def ingest_probe(savedvariables_path: str, addon: str | None = None) -> dict[str, Any]:
    from ..rules.runtime import load_probe, summarize_probe

    return summarize_probe(load_probe(check_path(savedvariables_path), addon))


def suppress_finding(path: str, rule_id: str, file: str, line: int, reason: str) -> dict[str, Any]:
    """Insert ``-- auditor:ignore RULE reason`` above ``file:line`` (merging with an existing one)."""
    load_rules()
    rid = rule_id.upper()
    if rid not in RULES:
        raise ToolError(f"unknown rule {rid}")
    reason = " ".join(reason.split())
    if len(reason) < 8:
        raise ToolError("a real reason is required (at least a short sentence)")
    root = _addon_root(path)
    target = (root / file).resolve()
    if root not in target.parents or target.suffix.lower() != ".lua" or not target.is_file():
        raise ToolError(f"{file} is not a Lua file inside {root}")
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    if not 1 <= line <= len(lines):
        raise ToolError(f"line {line} out of range (1..{len(lines)})")
    code = lines[line - 1]
    indent = code[: len(code) - len(code.lstrip())]
    newline = "\r\n" if code.endswith("\r\n") else "\n"
    prev = lines[line - 2] if line >= 2 else ""
    m = re.match(r"^(\s*)--\s*auditor:ignore\s+([A-Za-z0-9_*,]+)\s*(.*?)\s*$", prev)
    if m:
        ids = [i for i in m.group(2).split(",") if i]
        if rid not in ids:
            ids.append(rid)
        merged = f"{m.group(3)}; {reason}" if m.group(3) and reason not in m.group(3) else (m.group(3) or reason)
        lines[line - 2] = f"{m.group(1)}-- auditor:ignore {','.join(ids)} {merged}{newline}"
        action = "merged"
    else:
        lines.insert(line - 1, f"{indent}-- auditor:ignore {rid} {reason}{newline}")
        action = "inserted"
    target.write_text("".join(lines), encoding="utf-8")
    return {"file": str(target.relative_to(root)), "line": line, "rule_id": rid, "action": action,
            "note": "line numbers below this point shifted by one" if action == "inserted" else ""}


def update_baseline(path: str) -> dict[str, Any]:
    load_rules()
    root = _addon_root(path)
    findings = audit_all_findings(root)
    out = write_baseline(root, findings)
    return {"baseline": str(out), "accepted": len(findings)}


def record_learning(path: str, rule_id: str, verdict: str, note: str, file: str | None = None,
                    snippet: str | None = None) -> dict[str, Any]:
    if verdict not in VERDICTS:
        raise ToolError(f"verdict must be one of {VERDICTS}")
    if not _RULE_ID.match(rule_id.upper()):
        raise ToolError("rule_id must look like PERF001")
    root = _addon_root(path)
    from ..core.memory import redact

    p = append_learning(root, {"rule_id": rule_id.upper(), "verdict": verdict, "note": redact(note),
                               "file": file, "snippet": snippet})
    return {"recorded": str(p)}


def memory_hints(path: str, report: dict[str, Any] | None = None) -> dict[str, Any]:
    load_rules()
    root = _addon_root(path)
    if report is None:
        report = run_audit(root, AuditOptions(min_severity="info")).to_dict()
    return _memory_hints(root, report)
