"""Baseline (accepted legacy findings) and learnings (agent-recorded verdicts)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import STATE_DIR
from .finding import Finding

BASELINE_NAME = "baseline.json"
LEARNINGS_NAME = "learnings.jsonl"


def state_dir(addon_root: Path) -> Path:
    return addon_root / STATE_DIR


def load_baseline(addon_root: Path) -> set[str]:
    path = state_dir(addon_root) / BASELINE_NAME
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {e["fingerprint"] for e in data.get("findings", [])}


def write_baseline(addon_root: Path, findings: list[Finding]) -> Path:
    d = state_dir(addon_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / BASELINE_NAME
    payload = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "findings": [
            {"fingerprint": f.fingerprint, "rule_id": f.rule_id, "file": f.file, "line": f.line, "message": f.message}
            for f in sorted(findings, key=lambda f: (f.file or "", f.line or 0, f.rule_id))
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_learnings(addon_root: Path) -> list[dict[str, Any]]:
    path = state_dir(addon_root) / LEARNINGS_NAME
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def append_learning(addon_root: Path, entry: dict[str, Any]) -> Path:
    d = state_dir(addon_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / LEARNINGS_NAME
    entry = {"recorded": datetime.now(UTC).isoformat(timespec="seconds"), **entry}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path
