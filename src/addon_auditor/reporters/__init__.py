"""Report renderers."""

from __future__ import annotations

import json
from typing import Any

from ..core.engine import AuditResult
from ..core.finding import RULES

GITHUB_URL = "https://github.com/Terynas/addon-auditor/blob/main/"


def to_json(result: AuditResult, max_findings: int | None = None) -> str:
    return json.dumps(result.to_dict(max_findings), indent=2)


def to_sarif(result: AuditResult) -> str:
    level = {"error": "error", "warn": "warning", "info": "note"}
    used = sorted({f.rule_id for f in result.findings})
    rules: list[dict[str, Any]] = []
    for rid in used:
        r = RULES.get(rid)
        if r is None:
            continue
        rules.append({
            "id": rid,
            "name": r.meta.title,
            "shortDescription": {"text": r.meta.title},
            "fullDescription": {"text": r.meta.summary},
            "helpUri": GITHUB_URL + r.meta.doc,
            "defaultConfiguration": {"level": level[r.meta.severity]},
            "properties": {"category": r.meta.category, "tags": list(r.meta.tags)},
        })
    results = []
    for f in result.findings:
        res: dict[str, Any] = {
            "ruleId": f.rule_id,
            "level": level[f.severity],
            "message": {"text": f.message + (f"\nFix: {f.fix_hint}" if f.fix_hint else "")},
            "partialFingerprints": {"addonAuditor/v1": f.fingerprint},
            "properties": {"confidence": f.confidence, "category": f.category},
        }
        if f.file:
            region: dict[str, Any] = {}
            if f.line:
                region["startLine"] = f.line
                if f.end_line:
                    region["endLine"] = f.end_line
                if f.col:
                    region["startColumn"] = f.col
            loc: dict[str, Any] = {"artifactLocation": {"uri": f.file, "uriBaseId": "ADDONROOT"}}
            if region:
                loc["region"] = region
            res["locations"] = [{"physicalLocation": loc}]
        results.append(res)
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "addon-auditor", "informationUri": "https://github.com/Terynas/addon-auditor",
                                "rules": rules}},
            "originalUriBaseIds": {"ADDONROOT": {"uri": "file://" + result.root.rstrip("/") + "/"}},
            "results": results,
        }],
    }
    return json.dumps(sarif, indent=2)


_ICON = {"error": "ERROR", "warn": "WARN", "info": "info"}


def to_markdown(result: AuditResult, max_findings: int = 200) -> str:
    out: list[str] = []
    c = result.counts
    out.append(f"# addon-auditor: {result.addon}")
    out.append("")
    out.append(f"**Gate:** {result.gate.upper()} (fails on `{result.fail_on}`) · **Score:** {result.overall}/100 · "
               f"**Profiles:** {', '.join(result.profiles)}" + (" · **diff mode**" if result.diff_mode else ""))
    out.append("")
    out.append(f"{c.get('error', 0)} errors · {c.get('warn', 0)} warnings · {c.get('info', 0)} info"
               f" · {len(result.suppressed)} suppressed · {result.baselined} baselined"
               f" · {result.rules_run} rules · {result.duration_ms} ms")
    out.append("")
    out.append("| Category | Score |")
    out.append("|---|---|")
    for cat, s in sorted(result.scores.items(), key=lambda kv: kv[1]):
        out.append(f"| {cat} | {s} |")
    out.append("")
    if result.notes:
        out.append("## Notes")
        out.extend(f"- {n}" for n in result.notes)
        out.append("")
    if not result.findings:
        out.append("No findings.")
        return "\n".join(out) + "\n"
    out.append("## Findings")
    out.append("")
    for f in result.findings[:max_findings]:
        loc = f"{f.file}:{f.line}" if f.file and f.line else (f.file or "addon")
        out.append(f"- **{_ICON[f.severity]}** `{f.rule_id}` {loc} — {f.message}"
                   + (f" _(confidence: {f.confidence})_" if f.confidence != "high" else ""))
        if f.snippet:
            out.append(f"  - code: `{f.snippet}`")
        if f.fix_hint:
            out.append(f"  - fix: {f.fix_hint}")
    if len(result.findings) > max_findings:
        out.append(f"- … {len(result.findings) - max_findings} more (use JSON output for all)")
    return "\n".join(out) + "\n"
