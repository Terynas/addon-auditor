"""Run rules over an addon and post-process findings (suppressions, baseline, learnings, diff filter, scores)."""

from __future__ import annotations

import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import suppress
from .baseline import load_baseline, load_learnings
from .config import Config
from .context import AuditContext
from .finding import RULES, SEVERITY_RANK, Emit, Finding, RuleMeta

# Lower number wins when two findings describe the same symbol on the same line.
_DEDUPE_PRIORITY = {"api": 0, "security": 1, "perf": 2, "savedvars": 3, "ux": 4, "toc": 5, "packaging": 6, "lint": 9}

CATEGORY_WEIGHTS = {"error": 20.0, "warn": 6.0, "info": 1.0}
CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.7, "low": 0.4}


def load_rules() -> dict[str, Any]:
    from .. import rules  # noqa: F401  (registers every pack)

    return RULES


@dataclass
class AuditOptions:
    profiles: list[str] | None = None
    categories: list[str] | None = None
    rule_ids: list[str] | None = None
    min_severity: str | None = None
    changed: dict[str, set[int] | None] | None = None  # rel file -> changed lines (None = whole file)
    use_baseline: bool = True
    run_luacheck: bool = True
    probe_path: Path | None = None


@dataclass
class AuditResult:
    addon: str
    root: str
    profiles: list[str]
    findings: list[Finding]
    suppressed: list[dict[str, Any]] = field(default_factory=list)
    baselined: int = 0
    known_false_positives: int = 0
    scores: dict[str, int] = field(default_factory=dict)
    overall: int = 100
    gate: str = "pass"
    fail_on: str = "error"
    counts: dict[str, int] = field(default_factory=dict)
    rules_run: int = 0
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    diff_mode: bool = False

    def to_dict(self, max_findings: int | None = None) -> dict[str, Any]:
        fs = self.findings if max_findings is None else self.findings[:max_findings]
        return {
            "tool": "addon-auditor",
            "addon": self.addon,
            "root": self.root,
            "profiles": self.profiles,
            "gate": self.gate,
            "fail_on": self.fail_on,
            "overall_score": self.overall,
            "scores": self.scores,
            "counts": self.counts,
            "diff_mode": self.diff_mode,
            "baselined": self.baselined,
            "known_false_positives": self.known_false_positives,
            "suppressed": len(self.suppressed),
            "rules_run": self.rules_run,
            "duration_ms": self.duration_ms,
            "notes": self.notes,
            "truncated": max_findings is not None and len(self.findings) > max_findings,
            "findings": [f.to_dict() for f in fs],
        }


def _applies(meta: RuleMeta, ctx: AuditContext, opts: AuditOptions) -> bool:
    if opts.rule_ids and meta.id not in opts.rule_ids:
        return False
    if opts.categories and meta.category not in opts.categories:
        return False
    if not ctx.config.rule_enabled(meta.id, meta.category):
        return False
    if meta.profiles and not ctx.has_profile(*meta.profiles):
        return False
    if meta.category == "runtime" and ctx.probe is None:
        return False
    if meta.category == "lint" and not opts.run_luacheck and meta.id != "LINT001":
        return False
    return True


def _sort_key(f: Finding) -> tuple:
    return (-SEVERITY_RANK[f.severity], {"high": 0, "medium": 1, "low": 2}[f.confidence],
            f.category, f.file or "", f.line or 0)


def git_changed_lines(root: Path, ref: str) -> dict[str, set[int] | None]:
    """Changed lines per file vs ``ref`` (includes untracked files, whole-file)."""
    out: dict[str, set[int] | None] = {}
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True)
    if top.returncode != 0:
        raise RuntimeError(f"not a git repository: {root}")
    toplevel = Path(top.stdout.strip()).resolve()
    prefix = root.resolve().relative_to(toplevel).as_posix() if root.resolve() != toplevel else ""
    diff = subprocess.run(["git", "diff", "-U0", "--no-color", ref, "--", "."], cwd=root,
                          capture_output=True, text=True)
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr.strip() or f"git diff {ref} failed")
    current: str | None = None
    for line in diff.stdout.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path == "/dev/null":
                current = None
                continue
            path = path[2:] if path.startswith("b/") else path
            if prefix and path.startswith(prefix + "/"):
                path = path[len(prefix) + 1:]
            current = path
            out.setdefault(current, set())
        elif line.startswith("@@") and current is not None:
            hunk = line.split("+", 1)[1].split(" ", 1)[0]
            start, _, count = hunk.partition(",")
            n = int(count) if count else 1
            s = int(start)
            lines = out[current]
            if lines is not None:
                lines.update(range(s, s + max(n, 1)))
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=root,
                               capture_output=True, text=True)
    for path in untracked.stdout.splitlines():
        out[path.strip()] = None
    return out


def _in_changes(f: Finding, changed: dict[str, set[int] | None]) -> bool:
    if f.file is None:
        return False
    if f.file not in changed:
        return False
    lines = changed[f.file]
    if lines is None or f.line is None:
        return True
    lo, hi = f.line, f.end_line or f.line
    return any(n in lines for n in range(lo, hi + 1)) or any(lo <= n <= hi for n in lines)


def run_audit(path: Path, opts: AuditOptions | None = None, config: Config | None = None) -> AuditResult:
    opts = opts or AuditOptions()
    started = time.monotonic()
    rules = load_rules()
    ctx = AuditContext(path, config=config, profiles=opts.profiles)
    ctx.run_luacheck = opts.run_luacheck  # type: ignore[attr-defined]
    if opts.probe_path is not None:
        from ..rules.runtime import load_probe

        ctx.probe = load_probe(opts.probe_path, ctx.addon.name)

    raw: list[Finding] = []
    ran = 0
    notes: list[str] = []
    for r in rules.values():
        meta: RuleMeta = r.meta
        if not _applies(meta, ctx, opts):
            continue
        ran += 1
        try:
            if meta.scope == "addon":
                r.fn(ctx, Emit(meta, ctx, None, raw))
            else:
                for lf in ctx.parsed_files():
                    r.fn(ctx, lf, Emit(meta, ctx, lf, raw))
        except Exception as e:  # a broken rule must never kill the audit
            notes.append(f"rule {meta.id} crashed: {type(e).__name__}: {e}")
    notes.extend(getattr(ctx, "notes", []))

    # Dedupe: same file+line+symbol reported by several packs -> keep highest-priority category.
    by_key: dict[tuple, Finding] = {}
    findings: list[Finding] = []
    for f in raw:
        sym = next((t for t in f.tags if t.startswith("symbol:")), None)
        if sym is None:
            findings.append(f)
            continue
        key = (f.file, f.line, sym)
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = f
        elif _DEDUPE_PRIORITY.get(f.category, 5) < _DEDUPE_PRIORITY.get(prev.category, 5):
            by_key[key] = f
    findings.extend(by_key.values())

    # Fingerprints (stable across line shifts).
    occ: Counter[tuple] = Counter()
    for f in sorted(findings, key=lambda f: (f.file or "", f.line or 0, f.rule_id)):
        k = (f.rule_id, f.file, (f.snippet or "").strip(), f.message if not f.snippet else "")
        f.compute_fingerprint(occ[k])
        occ[k] += 1

    # Suppressions.
    kept: list[Finding] = []
    suppressed: list[dict[str, Any]] = []
    for f in findings:
        lf = ctx.files.get(f.file) if f.file else None
        s = suppress.find(lf.suppressions, f.rule_id, f.line, f.end_line) if lf else None
        if s is not None:
            s.used = True
            suppressed.append({"rule_id": f.rule_id, "file": f.file, "line": f.line, "reason": s.reason})
            continue
        kept.append(f)
    # Reasonless / unused suppressions are themselves findings.
    meta_rule = rules.get("META001")
    if meta_rule is not None and _applies(meta_rule.meta, ctx, opts):
        for lf in ctx.lua_files():
            for s in lf.suppressions:
                if not s.reason:
                    Emit(meta_rule.meta, ctx, lf, kept)(
                        s.comment_line, "Suppression has no reason. Write why the finding is acceptable.",
                        fix_hint="-- auditor:ignore PERF001 throttled by the caller (runs once per second)")

    # Baseline and learnings.
    baselined = 0
    if opts.use_baseline:
        base = load_baseline(ctx.root)
        if base:
            before = len(kept)
            kept = [f for f in kept if f.fingerprint not in base]
            baselined = before - len(kept)
    fp = 0
    for entry in load_learnings(ctx.root):
        if entry.get("verdict") != "false_positive":
            continue
        for f in kept:
            if f.rule_id == entry.get("rule_id") and (not entry.get("file") or entry.get("file") == f.file) \
                    and (not entry.get("snippet") or entry.get("snippet") == f.snippet):
                if "known-false-positive" not in f.tags:
                    f.severity = "info"
                    f.tags.append("known-false-positive")
                    fp += 1

    # Diff filter.
    diff_mode = opts.changed is not None
    if opts.changed is not None:
        kept = [f for f in kept if _in_changes(f, opts.changed)]

    min_sev = opts.min_severity or ctx.config.min_severity
    kept = [f for f in kept if SEVERITY_RANK[f.severity] >= SEVERITY_RANK[min_sev]]
    kept.sort(key=_sort_key)

    # Scores.
    from .finding import CATEGORIES

    penalty: dict[str, float] = {c: 0.0 for c in CATEGORIES if c != "meta"}
    for f in kept:
        if f.category in penalty and "known-false-positive" not in f.tags:
            penalty[f.category] += CATEGORY_WEIGHTS[f.severity] * CONFIDENCE_FACTOR[f.confidence]
    scores = {c: max(0, round(100 - p)) for c, p in penalty.items()}
    if ctx.probe is None:
        scores.pop("runtime", None)
    weights = {"perf": 2.0, "ux": 1.5, "security": 1.5, "api": 1.5}
    total_w = sum(weights.get(c, 1.0) for c in scores)
    overall = round(sum(s * weights.get(c, 1.0) for c, s in scores.items()) / total_w) if scores else 100

    fail_rank = SEVERITY_RANK[ctx.config.fail_on]
    gate = "fail" if any(SEVERITY_RANK[f.severity] >= fail_rank and "known-false-positive" not in f.tags
                         for f in kept) else "pass"
    counts = Counter(f.severity for f in kept)
    return AuditResult(
        addon=ctx.addon.name,
        root=str(ctx.root),
        profiles=sorted(ctx.profiles),
        findings=kept,
        suppressed=suppressed,
        baselined=baselined,
        known_false_positives=fp,
        scores=scores,
        overall=overall,
        gate=gate,
        fail_on=ctx.config.fail_on,
        counts={k: counts.get(k, 0) for k in ("error", "warn", "info")},
        rules_run=ran,
        duration_ms=int((time.monotonic() - started) * 1000),
        notes=notes,
        diff_mode=diff_mode,
    )


def audit_all_findings(path: Path, opts: AuditOptions | None = None) -> list[Finding]:
    """Every finding ignoring baseline -- used to write a new baseline."""
    o = opts or AuditOptions()
    o.use_baseline = False
    o.min_severity = "info"
    return run_audit(path, o).findings
