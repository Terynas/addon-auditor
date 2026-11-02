"""Meta rules: auditor housekeeping."""

from __future__ import annotations

from ..core.context import AuditContext, LuaFile
from ..core.finding import Emit, rule


@rule("META001", "meta", "warn", "Suppression without a reason",
      "`-- auditor:ignore` comments must say why the finding is acceptable, so the next agent does not "
      "re-open or blindly copy it. Emitted by the engine after suppressions are applied.")
def suppression_reason(ctx: AuditContext, lf: LuaFile, emit: Emit) -> None:
    return None
