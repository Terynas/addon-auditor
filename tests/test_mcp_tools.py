from __future__ import annotations

from pathlib import Path

import pytest

from addon_auditor.core.memory import redact
from addon_auditor.mcp import tools


def _addon(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "MyAddon"
    root.mkdir()
    (root / "MyAddon.toc").write_text("## Interface: 16001\n## Title: MyAddon\n\ncore.lua\n", encoding="utf-8")
    (root / "core.lua").write_text(body, encoding="utf-8")
    return root


def test_suppress_insert_then_merge(tmp_path: Path) -> None:
    root = _addon(tmp_path, "local x = 1\n  print(x)\n")
    r = tools.suppress_finding(str(root), "LINT005", "core.lua", 2, "kept for the debug build only")
    assert r["action"] == "inserted"
    tools.suppress_finding(str(root), "LINT006", "core.lua", 3, "shadowing is intentional here")
    lines = (root / "core.lua").read_text(encoding="utf-8").splitlines()
    assert lines[1].startswith("  -- auditor:ignore LINT005,LINT006 kept for the debug build only; shadowing")
    assert lines[2] == "  print(x)"


def test_suppress_requires_reason(tmp_path: Path) -> None:
    root = _addon(tmp_path, "local x = 1\n")
    with pytest.raises(tools.ToolError):
        tools.suppress_finding(str(root), "LINT005", "core.lua", 1, "ok")


def test_suppress_rejects_paths_outside_addon(tmp_path: Path) -> None:
    root = _addon(tmp_path, "local x = 1\n")
    (tmp_path / "other.lua").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(tools.ToolError):
        tools.suppress_finding(str(root), "LINT005", "../other.lua", 1, "should never be written")


def test_roots_restriction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _addon(tmp_path, "local x = 1\n")
    monkeypatch.setenv("ADDON_AUDITOR_ROOTS", str(tmp_path / "elsewhere"))
    with pytest.raises(tools.ToolError):
        tools.check_path(str(root))
    monkeypatch.setenv("ADDON_AUDITOR_ROOTS", str(tmp_path))
    assert tools.check_path(str(root)) == root.resolve()


def test_false_positive_learning_downgrades(tmp_path: Path) -> None:
    root = _addon(tmp_path, "local x = = 1\n")
    before = tools.audit_addon(str(root), rule_ids=["LINT001"], min_severity="info")
    assert before["gate"] == "fail"
    f = before["findings"][0]
    tools.record_learning(str(root), "LINT001", "false_positive", "fixture parses fine in-game",
                          file=f["file"], snippet=f.get("snippet"))
    after = tools.audit_addon(str(root), rule_ids=["LINT001"], min_severity="info")
    assert after["gate"] == "pass"
    assert "known-false-positive" in after["findings"][0]["tags"]


def test_memory_hints_lessons(tmp_path: Path) -> None:
    root = _addon(tmp_path, "local x = 1\n")
    tools.record_learning(str(root), "PERF001", "accepted", "throttled by caller; token=abc123 leaked")
    hints = tools.memory_hints(str(root), {"addon": "MyAddon", "findings": [], "gate": "pass",
                                           "overall_score": 100, "profiles": ["forever"]})
    assert hints["ingest_recommended"] is True
    assert "abc123" not in hints["lessons_markdown"]
    assert "MyAddon" in hints["search_queries"][0]


def test_redact() -> None:
    assert "s3cr3t" not in redact("password = s3cr3t")
    assert redact("plain words stay") == "plain words stay"


def test_check_api_validates_symbol() -> None:
    with pytest.raises(tools.ToolError):
        tools.check_api("os.execute('x')")
