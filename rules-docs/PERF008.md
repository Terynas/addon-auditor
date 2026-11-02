# PERF008: Repeated global lookups in a hot path

**Category:** perf

## Why

A global access (`UnitHealth`, `math.floor`) is a hash lookup in `_G` (plus one per `.` field) on every execution; a local or upvalue is an indexed slot read. The difference is tiny once but adds up in code that runs every frame or per frequent event, especially inside loops. Cache the APIs you use there in file-scope locals: `local floor, UnitHealth = math.floor, UnitHealth`. Reported at info/low confidence: it is a micro-optimisation, worth doing only in hot paths, which is the only place this rule looks.

## Bad

```lua
local f = CreateFrame("Frame")
local bars = {}

f:RegisterUnitEvent("UNIT_HEALTH", "player")
f:SetScript("OnEvent", function(self, event, unit)
  local pct = UnitHealth(unit) / UnitHealthMax(unit) * 100
  for i = 1, #bars do
    bars[i]:SetValue(math.floor(pct / 10))
  end
end)
```

## Good

```lua
local floor = math.floor
local UnitHealth, UnitHealthMax = UnitHealth, UnitHealthMax
local f = CreateFrame("Frame")
local bars = {}

f:RegisterUnitEvent("UNIT_HEALTH", "player")
f:SetScript("OnEvent", function(self, event, unit)
  local pct = UnitHealth(unit) / UnitHealthMax(unit) * 100
  for i = 1, #bars do
    bars[i]:SetValue(floor(pct / 10))
  end
end)
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- Lua Performance Tips (Roberto Ierusalimschy), section on locals
