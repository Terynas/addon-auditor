"""Per-addon configuration from ``.addon-auditor.toml``."""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .finding import SEVERITY_RANK, Severity

CONFIG_NAME = ".addon-auditor.toml"
STATE_DIR = ".addon-auditor"

DEFAULT_EXCLUDES = ["Libs/**", "libs/**", "Lib/**", "lib/**", "Libraries/**", ".git/**", ".github/**",
                    "spec/**", "tests/**", "test/**", ".tools/**", "node_modules/**", "dist/**", ".release/**"]

DEFAULT_THRESHOLDS: dict[str, float] = {
    # Probe / runtime thresholds
    "runtime_memory_kb_warn": 5_000.0,
    "runtime_memory_growth_kb_per_min_warn": 200.0,
    "runtime_cpu_ms_per_sec_warn": 1.0,
    "runtime_events_per_sec_warn": 200.0,
    # Static thresholds
    "max_file_lines_info": 3000.0,
    "max_function_lines_info": 200.0,
    "package_size_mb_warn": 20.0,
}


@dataclass
class Config:
    profiles: list[str] | None = None
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    include_libs: bool = False
    fail_on: Severity = "error"
    min_severity: Severity = "info"
    rules: dict[str, Any] = field(default_factory=dict)
    disabled_categories: list[str] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    extra_globals: list[str] = field(default_factory=list)
    path: Path | None = None

    def severity_for(self, rule_id: str, default: Severity) -> Severity | None:
        override = self.rules.get(rule_id)
        if override is None:
            return default
        if isinstance(override, dict):
            override = override.get("severity", default)
        if override in ("off", False, "disabled"):
            return None
        if override in SEVERITY_RANK:
            return override  # type: ignore[return-value]
        return default

    def rule_enabled(self, rule_id: str, category: str) -> bool:
        if category in self.disabled_categories:
            return False
        return self.severity_for(rule_id, "info") is not None

    def rule_option(self, rule_id: str, key: str, default: Any) -> Any:
        override = self.rules.get(rule_id)
        if isinstance(override, dict):
            return override.get(key, default)
        return default

    def threshold(self, key: str) -> float:
        return float(self.thresholds.get(key, DEFAULT_THRESHOLDS.get(key, 0.0)))

    def is_excluded(self, rel: str) -> bool:
        rel = rel.replace("\\", "/")
        for pat in self.exclude:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch("/" + rel, "*/" + pat):
                return True
        return False


def load_config(addon_root: Path) -> Config:
    cfg = Config()
    path = addon_root / CONFIG_NAME
    if not path.is_file():
        return cfg
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg.path = path
    if "profiles" in data:
        cfg.profiles = [str(p) for p in data["profiles"]]
    if "exclude" in data:
        cfg.exclude = list(DEFAULT_EXCLUDES) + [str(p) for p in data["exclude"]]
    cfg.include_libs = bool(data.get("include_libs", False))
    if cfg.include_libs:
        cfg.exclude = [p for p in cfg.exclude if not p.lower().startswith(("libs/", "lib/", "libraries/"))]
    if data.get("fail_on") in SEVERITY_RANK:
        cfg.fail_on = data["fail_on"]
    if data.get("min_severity") in SEVERITY_RANK:
        cfg.min_severity = data["min_severity"]
    cfg.rules = dict(data.get("rules", {}))
    cfg.disabled_categories = [str(c) for c in data.get("disabled_categories", [])]
    cfg.thresholds.update({k: float(v) for k, v in data.get("thresholds", {}).items()})
    cfg.extra_globals = [str(g) for g in data.get("globals", [])]
    return cfg
