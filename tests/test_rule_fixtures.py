"""Every registered rule needs docs plus a firing ``bad`` fixture and a quiet ``good`` fixture.

Layout: ``tests/fixtures/<category>/<RULE_ID>/{bad,good}/`` -- each is a tiny addon folder with a .toc.
When the addon name matters, use ``bad/MyAddon/MyAddon.toc`` instead.
Rules that need runtime data read ``probe.lua`` (AuditorProbe SavedVariables) from ``bad/`` or ``good/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from addon_auditor.adapters.luacheck import find_luacheck
from addon_auditor.core.engine import AuditOptions, load_rules, run_audit
from addon_auditor.core.finding import RULES

FIXTURES = Path(__file__).parent / "fixtures"
DOCS = Path(__file__).resolve().parents[1] / "rules-docs"

load_rules()
RULE_IDS = sorted(RULES)
# Rules exercised by dedicated tests instead of fixture folders.
SPECIAL = {"META001"}


def _addon_dir(folder: Path) -> Path:
    """``bad/`` may itself be the addon, or hold exactly one addon folder (``bad/MyAddon/MyAddon.toc``)."""
    if any(folder.glob("*.toc")):
        return folder
    subs = [d for d in folder.iterdir() if d.is_dir() and any(d.glob("*.toc"))]
    assert len(subs) == 1, f"{folder}: expected a .toc or exactly one addon sub-folder"
    return subs[0]


def _audit(folder: Path, rule_id: str):  # type: ignore[no-untyped-def]
    probe = folder / "probe.lua"
    folder = _addon_dir(folder)
    opts = AuditOptions(rule_ids=[rule_id], use_baseline=False, min_severity="info",
                        probe_path=probe if probe.is_file() else None)
    return run_audit(folder, opts)


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_rule_has_doc(rule_id: str) -> None:
    doc = DOCS / f"{rule_id}.md"
    assert doc.is_file(), f"missing {doc}"
    text = doc.read_text(encoding="utf-8")
    assert text.startswith(f"# {rule_id}"), "doc must start with '# <ID>: <title>'"
    for section in ("## Why", "## Bad", "## Good"):
        assert section in text, f"{doc.name} lacks '{section}'"


NEEDS_LUACHECK = {"LINT002", "LINT003", "LINT004", "LINT005", "LINT006", "LINT007", "LINT008"}
HAVE_LUACHECK = find_luacheck(FIXTURES) is not None


@pytest.mark.parametrize("rule_id", [r for r in RULE_IDS if r not in SPECIAL])
def test_bad_fixture_fires(rule_id: str) -> None:
    if rule_id in NEEDS_LUACHECK and not HAVE_LUACHECK:
        pytest.skip("luacheck not installed")
    meta = RULES[rule_id].meta
    folder = FIXTURES / meta.category / rule_id / "bad"
    assert folder.is_dir(), f"missing fixture {folder}"
    res = _audit(folder, rule_id)
    assert any(f.rule_id == rule_id for f in res.findings), f"{rule_id} did not fire on bad fixture: {res.notes}"


@pytest.mark.parametrize("rule_id", [r for r in RULE_IDS if r not in SPECIAL])
def test_good_fixture_quiet(rule_id: str) -> None:
    meta = RULES[rule_id].meta
    folder = FIXTURES / meta.category / rule_id / "good"
    assert folder.is_dir(), f"missing fixture {folder}"
    res = _audit(folder, rule_id)
    hits = [f for f in res.findings if f.rule_id == rule_id]
    assert not hits, f"{rule_id} fired on good fixture: {[(h.file, h.line, h.message) for h in hits]}"


@pytest.mark.parametrize("variant,expect", [("bad", True), ("good", False)])
def test_meta001_suppression_reason(variant: str, expect: bool) -> None:
    folder = FIXTURES / "meta" / "META001" / variant
    res = run_audit(folder, AuditOptions(use_baseline=False, min_severity="info"))
    assert any(f.rule_id == "META001" for f in res.findings) is expect
