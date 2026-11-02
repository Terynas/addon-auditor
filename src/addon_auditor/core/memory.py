"""Memory loop helpers: what to recall before an audit and what to remember after it.

The engine never talks to a memory service. It returns search queries and an ingest-ready lessons
document; the calling agent decides whether to send them to Hindsight (or any other store). Without a
memory service, ``.addon-auditor/learnings.jsonl`` is the fallback the engine reads on every audit.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .baseline import load_learnings
from .finding import RULES

_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|bearer|authorization)\b(\s*[:=]\s*|\s+)(\S+)"
)
_LONG_HEX = re.compile(r"\b[A-Fa-f0-9]{32,}\b|\b[A-Za-z0-9_\-]{40,}\b")

RECURRING_MIN = 3


def redact(text: str) -> str:
    text = _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    return _LONG_HEX.sub("[REDACTED]", text)


def _title(rule_id: str) -> str:
    r = RULES.get(rule_id)
    return r.meta.title if r else rule_id


def memory_hints(addon_root: Path, report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build recall queries and a lessons document from an audit report (``AuditResult.to_dict()``)
    plus the addon's recorded learnings."""
    addon = (report or {}).get("addon") or addon_root.name
    findings: list[dict[str, Any]] = list((report or {}).get("findings", []))
    learnings = load_learnings(addon_root)

    by_rule = Counter(f["rule_id"] for f in findings)
    top_rules = [rid for rid, _ in by_rule.most_common(5)]
    queries = [f"{addon} addon-auditor audit decisions", f"{addon} known false positives"]
    queries += [f"{rid} {_title(rid)} WoW addon fix" for rid in top_rules[:3]]

    recurring = [(rid, n) for rid, n in by_rule.most_common() if n >= RECURRING_MIN]
    fps = [e for e in learnings if e.get("verdict") == "false_positive"]
    accepted = [e for e in learnings if e.get("verdict") in ("accepted", "pattern")]
    fixed = [e for e in learnings if e.get("verdict") == "fixed"]
    suppressions = (report or {}).get("suppressed_detail", [])

    today = datetime.now(UTC).date().isoformat()
    lines = [f"# addon-auditor lessons: {addon} ({today})", ""]
    if report:
        lines += [f"Gate **{report.get('gate')}**, score {report.get('overall_score')}/100, "
                  f"profiles {', '.join(report.get('profiles', []))}.", ""]
    if recurring:
        lines.append("## Recurring findings")
        lines += [f"- {rid} ({_title(rid)}): {n} occurrences" for rid, n in recurring]
        lines.append("")
    if fps:
        lines.append("## Confirmed false positives (do not re-report)")
        lines += [f"- {e.get('rule_id')}{' in ' + e['file'] if e.get('file') else ''}: {e.get('note', '')}" for e in fps]
        lines.append("")
    if accepted:
        lines.append("## Accepted trade-offs and patterns")
        lines += [f"- {e.get('rule_id')}: {e.get('note', '')}" for e in accepted]
        lines.append("")
    if fixed:
        lines.append("## Fixed mistakes worth remembering")
        lines += [f"- {e.get('rule_id')}: {e.get('note', '')}" for e in fixed]
        lines.append("")
    if suppressions:
        lines.append("## Inline suppressions")
        lines += [f"- {s['rule_id']} {s.get('file')}:{s.get('line')}: {s.get('reason') or '(no reason)'}"
                  for s in suppressions]
        lines.append("")

    has_lessons = bool(recurring or fps or accepted or fixed or suppressions)
    return {
        "addon": addon,
        "search_queries": queries,
        "ingest_recommended": has_lessons,
        "document_title": f"addon-auditor lessons — {addon} — {today}",
        "lessons_markdown": redact("\n".join(lines).rstrip() + "\n") if has_lessons else "",
        "learnings_file": str(addon_root / ".addon-auditor" / "learnings.jsonl"),
        "learnings_count": len(learnings),
        "instructions": (
            "Before auditing: search your memory with search_queries and honour recorded false positives. "
            "After fixing: if ingest_recommended, store lessons_markdown under document_title in your memory "
            "service, and record per-finding verdicts with record_learning so the engine can use them "
            "without a memory service."
        ),
    }
