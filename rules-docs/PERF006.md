# PERF006: UNIT_* event filtered in Lua instead of RegisterUnitEvent

**Category:** perf

## Why

`RegisterEvent("UNIT_HEALTH")` delivers the event for every unit the client tracks: party and raid members, pets, targets of targets, every nameplate. In a raid that is dozens of Lua calls per second that immediately `return` because the unit is not `player`. `RegisterUnitEvent(event, unit1[, unit2])` filters in C, so Lua only wakes for the units you care about.

Reported only when every handler for the event starts with a fixed-unit guard (`if unit ~= "player" then return end`) or handles it only in `event == X and unit == "u"` branches, for at most two units (the RegisterUnitEvent limit). Skipped for AceEvent addons.

## Bad

```lua
local f = CreateFrame("Frame")
local function UpdatePlayerHealth()
  print(UnitHealth("player"))
end

f:RegisterEvent("UNIT_HEALTH")
f:SetScript("OnEvent", function(self, event, unit)
  if unit ~= "player" then return end
  UpdatePlayerHealth()
end)
```

## Good

```lua
local f = CreateFrame("Frame")
local function UpdatePlayerHealth()
  print(UnitHealth("player"))
end

f:RegisterUnitEvent("UNIT_HEALTH", "player")
f:SetScript("OnEvent", function(self, event, unit)
  UpdatePlayerHealth()
end)
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- First Timers `06-notes/addon-dev/api-events-frames.md`
- Warcraft Wiki: Frame:RegisterUnitEvent
