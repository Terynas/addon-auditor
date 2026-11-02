# PERF010: SavedVariables list grows without bound

**Category:** perf

## Why

SavedVariables are executed as Lua at login and serialized at logout. A list that gets a new entry every session (or every event) and is never trimmed makes every login, logout and /reload slower forever and keeps the whole history in memory. Cap lists after inserting (`while #t > N do table.remove(t, 1) end`) or prune old entries at login.

Recognises SavedVariables names from the TOC and aliases such as `ns.db = MyDB` / `local db = MyDB`. Any `table.remove`, `wipe`, `#t > N` check, reset to `{}` or `t[k] = nil` on the same list anywhere in the addon counts as trimming; inserts guarded by a dedupe check (`if not seen[x]`, `tContains`) are skipped.

## Bad

```lua
local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function()
  FixtureDB = FixtureDB or {}
  FixtureDB.logins = FixtureDB.logins or {}
  table.insert(FixtureDB.logins, { when = time(), zone = GetRealZoneText() })
end)
```

## Good

```lua
local MAX_LOGINS = 50
local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function()
  FixtureDB = FixtureDB or {}
  FixtureDB.logins = FixtureDB.logins or {}
  table.insert(FixtureDB.logins, { when = time(), zone = GetRealZoneText() })
  while #FixtureDB.logins > MAX_LOGINS do
    table.remove(FixtureDB.logins, 1)
  end
end)
```

## References

- First Timers `06-notes/addon-dev/savedvariables-and-load-order.md`
- First Timers `06-notes/addon-dev/performance-and-resources.md`
