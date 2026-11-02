"""Finding model and rule registry."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .context import AuditContext, LuaFile

Severity = Literal["error", "warn", "info"]
Confidence = Literal["high", "medium", "low"]

SEVERITY_RANK: dict[str, int] = {"info": 0, "warn": 1, "error": 2}
CATEGORIES = ("lint", "toc", "api", "perf", "security", "savedvars", "ux", "packaging", "runtime", "meta")


@dataclass
class Finding:
    rule_id: str
    category: str
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None
    end_line: int | None = None
    col: int | None = None
    confidence: Confidence = "high"
    fix_hint: str | None = None
    title: str = ""
    doc: str = ""
    snippet: str | None = None
    tags: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def compute_fingerprint(self, occurrence: int = 0) -> str:
        text = (self.snippet or "").strip()
        raw = f"{self.rule_id}|{self.file or ''}|{text}|{self.message if not text else ''}|{occurrence}"
        self.fingerprint = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        return self.fingerprint

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, [], "")}


@dataclass(frozen=True)
class RuleMeta:
    id: str
    category: str
    severity: Severity
    title: str
    summary: str
    scope: Literal["file", "addon"] = "file"
    confidence: Confidence = "high"
    profiles: tuple[str, ...] | None = None  # None = all
    tags: tuple[str, ...] = ()

    @property
    def doc(self) -> str:
        return f"rules-docs/{self.id}.md"


class Emit:
    """Callable handed to rules to report findings."""

    def __init__(self, meta: RuleMeta, ctx: AuditContext, lf: LuaFile | None, sink: list[Finding]) -> None:
        self.meta = meta
        self.ctx = ctx
        self.lf = lf
        self.sink = sink

    def __call__(
        self,
        line: int | None,
        message: str,
        *,
        fix_hint: str | None = None,
        severity: Severity | None = None,
        confidence: Confidence | None = None,
        end_line: int | None = None,
        col: int | None = None,
        file: str | None = None,
        tags: Iterable[str] = (),
    ) -> None:
        rel = file if file is not None else (self.lf.rel if self.lf else None)
        snippet = None
        if rel and line:
            snippet = self.ctx.source_line(rel, line)
        sev = self.ctx.config.severity_for(self.meta.id, severity or self.meta.severity)
        if sev is None:
            return
        self.sink.append(Finding(
            rule_id=self.meta.id,
            category=self.meta.category,
            severity=sev,
            message=message,
            file=rel,
            line=line,
            end_line=end_line if end_line and end_line != line else None,
            col=col,
            confidence=confidence or self.meta.confidence,
            fix_hint=fix_hint,
            title=self.meta.title,
            doc=self.meta.doc,
            snippet=snippet.strip()[:200] if snippet else None,
            tags=list(self.meta.tags) + list(tags),
        ))


FileCheck = Callable[["AuditContext", "LuaFile", Emit], None]
AddonCheck = Callable[["AuditContext", Emit], None]


@dataclass
class Rule:
    meta: RuleMeta
    fn: Callable[..., None]


RULES: dict[str, Rule] = {}


def rule(
    id: str,
    category: str,
    severity: Severity,
    title: str,
    summary: str,
    *,
    scope: Literal["file", "addon"] = "file",
    confidence: Confidence = "high",
    profiles: tuple[str, ...] | None = None,
    tags: tuple[str, ...] = (),
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Register a rule. File-scope rules get ``(ctx, lf, emit)``; addon-scope rules get ``(ctx, emit)``."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category}")

    def deco(fn: Callable[..., None]) -> Callable[..., None]:
        if id in RULES:
            raise ValueError(f"duplicate rule id {id}")
        RULES[id] = Rule(RuleMeta(id, category, severity, title, summary, scope, confidence, profiles, tags), fn)
        return fn

    return deco
