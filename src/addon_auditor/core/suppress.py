"""Inline suppressions.

``-- auditor:ignore PERF001,UX003 <reason>`` on the offending line (trailing comment), or on its own
line directly above it. ``-- auditor:ignore-file PERF001 <reason>`` anywhere in the file.
``*`` matches every rule. A reason is required; reasonless suppressions are reported as META001.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lua_ast import Comment

_RE = re.compile(r"^\s*auditor:(ignore(?:-file)?)\s+([A-Za-z0-9_*,]+)\s*(.*)$")


@dataclass
class Suppression:
    rules: set[str]
    line: int  # line the suppression applies to (0 for whole file)
    reason: str
    comment_line: int
    used: bool = False

    def matches(self, rule_id: str) -> bool:
        return "*" in self.rules or rule_id in self.rules


def collect(comments: list[Comment], source_lines: list[str]) -> list[Suppression]:
    out: list[Suppression] = []
    for c in comments:
        m = _RE.match(c.text)
        if not m:
            continue
        kind, ids, reason = m.groups()
        rules = {r.strip().upper() if r.strip() != "*" else "*" for r in ids.split(",") if r.strip()}
        reason = reason.strip().lstrip("-:— ").strip()
        if kind == "ignore-file":
            out.append(Suppression(rules, 0, reason, c.line))
            continue
        text = source_lines[c.line - 1] if 0 < c.line <= len(source_lines) else ""
        own_line = text.strip().startswith("--")
        target = c.end_line + 1 if own_line else c.line
        if own_line:
            # skip blank lines between comment and code
            while target <= len(source_lines) and not source_lines[target - 1].strip():
                target += 1
        out.append(Suppression(rules, target, reason, c.line))
    return out


def find(suppressions: list[Suppression], rule_id: str, line: int | None, end_line: int | None) -> Suppression | None:
    for s in suppressions:
        if not s.matches(rule_id):
            continue
        if s.line == 0:
            return s
        if line is None:
            continue
        hi = end_line or line
        if line <= s.line <= hi or s.line == line:
            return s
    return None
