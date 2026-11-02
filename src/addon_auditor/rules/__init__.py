"""Rule packs. Importing this package registers every rule in ``core.finding.RULES``."""

from importlib import import_module

PACKS = ("meta", "lint", "toc", "packaging", "api", "perf", "security", "savedvars", "ux", "runtime")

for _pack in PACKS:
    import_module(f"{__name__}.{_pack}")
