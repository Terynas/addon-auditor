"""Command line interface: ``addon-auditor audit|diff|explain|rules|baseline|api|probe-ingest|learn``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core.engine import AuditOptions, audit_all_findings, git_changed_lines, load_rules, run_audit
from .core.finding import RULES, SEVERITY_RANK


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("path", nargs="?", default=".", type=Path, help="addon directory (or any file inside it)")
    p.add_argument("--profile", action="append", dest="profiles",
                   help="override client profiles: forever, classic-era, classic, mainline (repeatable)")
    p.add_argument("--category", action="append", dest="categories", help="only these categories (repeatable)")
    p.add_argument("--rule", action="append", dest="rule_ids", help="only these rule IDs (repeatable)")
    p.add_argument("--min-severity", choices=list(SEVERITY_RANK), help="hide findings below this severity")
    p.add_argument("--format", choices=["markdown", "json", "sarif"], default="markdown")
    p.add_argument("--output", "-o", type=Path, help="write report to file")
    p.add_argument("--no-baseline", action="store_true", help="ignore .addon-auditor/baseline.json")
    p.add_argument("--no-luacheck", action="store_true", help="skip luacheck")
    p.add_argument("--probe", type=Path, help="AuditorProbe SavedVariables file for runtime rules")


def _emit(result, fmt: str, output: Path | None) -> None:  # type: ignore[no-untyped-def]
    from .reporters import to_json, to_markdown, to_sarif

    text = {"json": to_json, "sarif": to_sarif, "markdown": to_markdown}[fmt](result)
    if output:
        output.write_text(text, encoding="utf-8")
        print(f"wrote {output} ({result.gate}, {len(result.findings)} findings)", file=sys.stderr)
    else:
        sys.stdout.write(text)


def _opts(args: argparse.Namespace) -> AuditOptions:
    return AuditOptions(profiles=args.profiles, categories=args.categories, rule_ids=args.rule_ids,
                        min_severity=args.min_severity, use_baseline=not args.no_baseline,
                        run_luacheck=not args.no_luacheck, probe_path=args.probe)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="addon-auditor", description="Audit World of Warcraft addons.")
    ap.add_argument("--version", action="version", version=f"addon-auditor {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_audit = sub.add_parser("audit", help="full audit (exit 1 when the gate fails)")
    _common(p_audit)

    p_diff = sub.add_parser("diff", help="audit only changed lines (vs git ref or listed files)")
    _common(p_diff)
    p_diff.add_argument("--ref", default="HEAD", help="git ref to diff against (default HEAD)")
    p_diff.add_argument("--files", nargs="*", help="explicit changed files (relative to addon root)")

    p_explain = sub.add_parser("explain", help="show a rule's documentation")
    p_explain.add_argument("rule_id")

    p_rules = sub.add_parser("rules", help="list rules")
    p_rules.add_argument("--category")
    p_rules.add_argument("--json", action="store_true")

    p_base = sub.add_parser("baseline", help="accept all current findings into .addon-auditor/baseline.json")
    p_base.add_argument("path", nargs="?", default=".", type=Path)

    p_api = sub.add_parser("api", help="check whether an API symbol exists per client")
    p_api.add_argument("symbol")

    p_rc = sub.add_parser("luacheckrc", help="print (or write) a compact .luacheckrc tailored to the addon")
    p_rc.add_argument("path", nargs="?", default=".", type=Path)
    p_rc.add_argument("--write", action="store_true", help="write <addon>/.luacheckrc (refuses to overwrite)")

    p_probe = sub.add_parser("probe-ingest", help="summarise AuditorProbe SavedVariables")
    p_probe.add_argument("savedvariables", type=Path)
    p_probe.add_argument("--addon", help="only this addon")

    p_learn = sub.add_parser("learn", help="record a verdict about a finding in .addon-auditor/learnings.jsonl")
    p_learn.add_argument("path", type=Path)
    p_learn.add_argument("rule_id")
    p_learn.add_argument("verdict", choices=["false_positive", "accepted", "fixed", "pattern"])
    p_learn.add_argument("note")
    p_learn.add_argument("--file")
    p_learn.add_argument("--snippet")

    args = ap.parse_args(argv)
    load_rules()

    if args.cmd in ("audit", "diff"):
        opts = _opts(args)
        if args.cmd == "diff":
            from .core.context import find_addon_root

            root = find_addon_root(args.path)
            if args.files:
                opts.changed = {f.replace("\\", "/"): None for f in args.files}
            else:
                opts.changed = git_changed_lines(root, args.ref)
        result = run_audit(args.path, opts)
        _emit(result, args.format, args.output)
        return 1 if result.gate == "fail" else 0

    if args.cmd == "explain":
        from .rules_docs import read_doc

        rid = args.rule_id.upper()
        if rid not in RULES:
            print(f"unknown rule {rid}", file=sys.stderr)
            return 2
        print(read_doc(rid))
        return 0

    if args.cmd == "rules":
        rows = [r.meta for r in RULES.values() if not args.category or r.meta.category == args.category]
        if args.json:
            print(json.dumps([{"id": m.id, "category": m.category, "severity": m.severity, "title": m.title,
                               "summary": m.summary, "profiles": m.profiles} for m in rows], indent=2))
        else:
            for m in rows:
                prof = f" [{','.join(m.profiles)}]" if m.profiles else ""
                print(f"{m.id:<8} {m.category:<10} {m.severity:<5} {m.title}{prof}")
        return 0

    if args.cmd == "baseline":
        from .core.baseline import write_baseline
        from .core.context import find_addon_root

        root = find_addon_root(args.path)
        findings = audit_all_findings(root)
        path = write_baseline(root, findings)
        print(f"baselined {len(findings)} findings -> {path}")
        return 0

    if args.cmd == "api":
        from .adapters.api_index import ApiIndex

        print(json.dumps(ApiIndex.for_profiles(set()).lookup(args.symbol), indent=2))
        return 0

    if args.cmd == "luacheckrc":
        from .adapters.luacheck import addon_template
        from .core.config import load_config
        from .core.context import AuditContext, find_addon_root
        from .rules.lint import allowed_globals, used_client_globals

        root = find_addon_root(args.path)
        ctx = AuditContext(root, load_config(root))
        text = addon_template(ctx.addon.name, ctx.profiles, allowed_globals(ctx), used_client_globals(ctx))
        if not args.write:
            sys.stdout.write(text)
            return 0
        dest = root / ".luacheckrc"
        if dest.exists():
            print(f"{dest} exists; not overwriting", file=sys.stderr)
            return 1
        dest.write_text(text, encoding="utf-8")
        print(f"wrote {dest}")
        return 0

    if args.cmd == "probe-ingest":
        from .rules.runtime import load_probe, summarize_probe

        data = load_probe(args.savedvariables, args.addon)
        print(json.dumps(summarize_probe(data), indent=2))
        return 0

    if args.cmd == "learn":
        from .core.baseline import append_learning
        from .core.context import find_addon_root

        root = find_addon_root(args.path)
        p = append_learning(root, {"rule_id": args.rule_id.upper(), "verdict": args.verdict, "note": args.note,
                                   "file": args.file, "snippet": args.snippet})
        print(f"recorded in {p}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
