"""Locate and read ``rules-docs/<ID>.md`` (repo checkout or installed wheel)."""

from __future__ import annotations

from pathlib import Path

from .core.finding import RULES

_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "rules-docs",  # source checkout
    Path(__file__).resolve().parent / "rules_docs",  # wheel (force-include)
]


def doc_path(rule_id: str) -> Path | None:
    for d in _CANDIDATES:
        p = d / f"{rule_id}.md"
        if p.is_file():
            return p
    return None


def read_doc(rule_id: str) -> str:
    p = doc_path(rule_id)
    if p is not None:
        return p.read_text(encoding="utf-8")
    r = RULES.get(rule_id)
    if r is None:
        return f"Unknown rule {rule_id}."
    m = r.meta
    return f"# {m.id}: {m.title}\n\nCategory: {m.category} · Severity: {m.severity}\n\n{m.summary}\n"
