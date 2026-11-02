# PERF007: COMBAT_LOG_EVENT_UNFILTERED handler

**Category:** perf

## Why

CLEU fires for every combat-log line within range: every hit, heal, aura application and periodic tick from every combatant. That is thousands of events per minute in a raid, so any work done before the subevent filter, and any allocation, is multiplied by that rate. Read `CombatLogGetCurrentEventInfo()` once, return immediately for subevents/GUIDs you do not need, and unregister outside the content that needs it. On clients where CLEU is restricted the API pack reports the registration instead (findings are deduplicated).

## Bad

```lua
local f = CreateFrame("Frame")
f:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")
f:SetScript("OnEvent", function()
  local _, subevent, _, sourceGUID = CombatLogGetCurrentEventInfo()
  if subevent ~= "SPELL_INTERRUPT" or sourceGUID ~= UnitGUID("player") then return end
  print("Interrupted!")
end)
```

## Good

```lua
local f = CreateFrame("Frame")
f:RegisterUnitEvent("UNIT_SPELLCAST_SUCCEEDED", "player")
f:SetScript("OnEvent", function(self, event, unit, castGUID, spellID)
  if spellID == 6552 then
    print("Pummel used")
  end
end)
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- First Timers `06-notes/addon-dev/midnight-12.md`
- Warcraft Wiki: COMBAT_LOG_EVENT
