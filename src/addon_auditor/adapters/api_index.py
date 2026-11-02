"""Known-API index per client profile, from bundled name data (see scripts/build_api_data.py).

Users can point ``ADDON_AUDITOR_API_DIR`` at a directory with fresher ``api-<profile>.json.gz`` files.
"""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..core.builtins import ALWAYS_KNOWN

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass
class ProfileApi:
    profile: str
    globals: frozenset[str]
    members: dict[str, frozenset[str]]
    deprecated: frozenset[str]
    sources: list[str] = field(default_factory=list)


@lru_cache(maxsize=8)
def load_profile(profile: str) -> ProfileApi | None:
    dirs = []
    if os.environ.get("ADDON_AUDITOR_API_DIR"):
        dirs.append(Path(os.environ["ADDON_AUDITOR_API_DIR"]))
    dirs.append(DATA_DIR)
    for d in dirs:
        path = d / f"api-{profile}.json.gz"
        if path.is_file():
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            return ProfileApi(
                profile=profile,
                globals=frozenset(data["globals"]),
                members={k: frozenset(v) for k, v in data["members"].items()},
                deprecated=frozenset(data.get("deprecated", [])),
                sources=list(data.get("sources", [])),
            )
    return None


class ApiIndex:
    """Lookup across the addon's target profiles."""

    def __init__(self, profiles: dict[str, ProfileApi | None]) -> None:
        self.profiles = profiles

    @classmethod
    def for_profiles(cls, names: set[str] | list[str]) -> ApiIndex:
        return cls({p: load_profile(p) for p in sorted(names)})

    @property
    def covered(self) -> list[str]:
        return [p for p, api in self.profiles.items() if api is not None]

    @property
    def uncovered(self) -> list[str]:
        return [p for p, api in self.profiles.items() if api is None]

    def global_in(self, name: str) -> dict[str, bool]:
        out = {}
        for p, api in self.profiles.items():
            if api is not None:
                out[p] = name in ALWAYS_KNOWN or name in api.globals
        return out

    def namespace_known(self, ns: str) -> dict[str, bool]:
        return {p: ns in api.members for p, api in self.profiles.items() if api is not None}

    def member_in(self, ns: str, member: str) -> dict[str, bool]:
        out = {}
        for p, api in self.profiles.items():
            if api is not None:
                out[p] = member in api.members.get(ns, frozenset())
        return out

    def deprecated(self, name: str) -> list[str]:
        return [p for p, api in self.profiles.items() if api is not None and name in api.deprecated]

    def lookup(self, symbol: str) -> dict[str, object]:
        """Human/agent-facing lookup used by ``check_api``."""
        result: dict[str, object] = {"symbol": symbol, "profiles": {}}
        for p in ("forever", "classic-era", "classic", "mainline"):
            api = load_profile(p)
            if api is None:
                result["profiles"][p] = "no data"  # type: ignore[index]
                continue
            if "." in symbol:
                ns, _, member = symbol.partition(".")
                known = member in api.members.get(ns, frozenset())
            else:
                known = symbol in ALWAYS_KNOWN or symbol in api.globals
            status = "exists" if known else "missing"
            if symbol in api.deprecated:
                status = "deprecated"
            result["profiles"][p] = status  # type: ignore[index]
        return result
