from __future__ import annotations

import json
from pathlib import Path

from addon_auditor.cli import main
from addon_auditor.core.engine import AuditOptions, run_audit
from addon_auditor.reporters import to_json, to_markdown, to_sarif


def make_addon(tmp: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp / name
    root.mkdir()
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


TOC = "## Interface: 16001, 120107\n## Title: Demo\n## Notes: demo\n## Version: 1.0\n## SavedVariables: DemoDB\n\ncore.lua\n"


def test_discovers_profiles_and_files(tmp_path: Path) -> None:
    root = make_addon(tmp_path, "Demo", {"Demo.toc": TOC, "core.lua": "local x = 1\n"})
    res = run_audit(root, AuditOptions(run_luacheck=False))
    assert res.profiles == ["forever", "mainline"]
    assert res.addon == "Demo"


def test_syntax_error_reported_and_gate_fails(tmp_path: Path) -> None:
    root = make_addon(tmp_path, "Demo", {"Demo.toc": TOC, "core.lua": "local x = = 1\n"})
    res = run_audit(root, AuditOptions(run_luacheck=False, rule_ids=["LINT001"]))
    assert res.gate == "fail"
    assert res.findings[0].rule_id == "LINT001"


def test_inline_suppression_requires_reason(tmp_path: Path) -> None:
    root = make_addon(tmp_path, "Demo", {
        "Demo.toc": TOC,
        "core.lua": "-- auditor:ignore LINT001\nlocal x = = 1\n",
    })
    res = run_audit(root, AuditOptions(run_luacheck=False, rule_ids=["LINT001", "META001"]))
    ids = [f.rule_id for f in res.findings]
    assert "LINT001" not in ids
    assert "META001" in ids


def test_reporters_render(tmp_path: Path) -> None:
    root = make_addon(tmp_path, "Demo", {"Demo.toc": TOC, "core.lua": "local x = = 1\n"})
    res = run_audit(root, AuditOptions(run_luacheck=False, rule_ids=["LINT001"]))
    assert json.loads(to_json(res))["gate"] == "fail"
    sarif = json.loads(to_sarif(res))
    assert sarif["runs"][0]["results"][0]["ruleId"] == "LINT001"
    assert "LINT001" in to_markdown(res)


def test_diff_filter_only_changed_lines(tmp_path: Path) -> None:
    root = make_addon(tmp_path, "Demo", {"Demo.toc": TOC, "core.lua": "local x = = 1\n"})
    opts = AuditOptions(run_luacheck=False, rule_ids=["LINT001"], changed={"other.lua": None})
    assert run_audit(root, opts).findings == []


def test_baseline_hides_known_findings(tmp_path: Path) -> None:
    root = make_addon(tmp_path, "Demo", {"Demo.toc": TOC, "core.lua": "local x = = 1\n"})
    assert main(["baseline", str(root)]) == 0
    res = run_audit(root, AuditOptions(run_luacheck=False, rule_ids=["LINT001"]))
    assert res.findings == [] and res.baselined == 1


def test_cli_rules_lists(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["rules"]) == 0
    assert "LINT001" in capsys.readouterr().out


def test_accidental_global_fallback_without_luacheck(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from addon_auditor.adapters import luacheck
    from addon_auditor.core.engine import AuditOptions, run_audit

    root = tmp_path / "Leaky"
    root.mkdir()
    (root / "Leaky.toc").write_text("## Interface: 16001\n## SavedVariables: LeakyDB\n\ncore.lua\n", encoding="utf-8")
    (root / "core.lua").write_text("LeakyDB = LeakyDB or {}\nlocal function F()\n  oops = 1\nend\nF()\n",
                                   encoding="utf-8")
    monkeypatch.setattr(luacheck, "find_luacheck", lambda start=None: None)
    res = run_audit(root, AuditOptions(rule_ids=["LINT003"], use_baseline=False, min_severity="info"))
    assert [(f.line, f.confidence) for f in res.findings] == [(3, "medium")]
