from __future__ import annotations

from pathlib import Path

from addon_auditor.core.engine import AuditOptions, run_audit
from addon_auditor.rules.runtime import load_probe, summarize_probe

ROOT = Path(__file__).resolve().parents[1]


def test_probe_addon_passes_its_own_audit() -> None:
    res = run_audit(ROOT / "probe" / "AuditorProbe", AuditOptions(use_baseline=False, min_severity="warn"))
    assert res.gate == "pass"
    assert not res.findings, [(f.rule_id, f.file, f.line, f.message) for f in res.findings]


def test_probe_ingest_summary() -> None:
    data = load_probe(ROOT / "tests/fixtures/runtime/RUN003/bad/probe.lua", None)
    s = summarize_probe(data)["addons"]["bad"]
    assert s["memory_growth_kb_per_min"] == 300.0
    assert s["events_per_sec"] > 0
