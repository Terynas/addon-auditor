"""RUNTIME rule pack: findings from AuditorProbe SavedVariables (filled in by the probe milestone)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_probe(path: Path, addon: str | None) -> dict[str, Any]:
    raise NotImplementedError


def summarize_probe(data: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError
