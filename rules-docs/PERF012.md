# PERF012: Polling state that has an event

**Category:** perf

## Why

Re-reading a value (`GetMoney()`, `UnitHealth()`, zone text, group size ...) from OnUpdate or a ticker and comparing it with a cached copy costs a C call and a comparison every tick, even though nothing changed for minutes. The client already announces those changes with events (PLAYER_MONEY, UNIT_HEALTH, ZONE_CHANGED_NEW_AREA, GROUP_ROSTER_UPDATE ...): register the event and update from its handler. Low confidence: some UIs poll on purpose for smooth animation.

## Bad

```lua
local lastMoney
local f = CreateFrame("Frame")
f:SetScript("OnUpdate", function(self, elapsed)
  self.t = (self.t or 0) + elapsed
  if self.t < 0.5 then return end
  self.t = 0
  local money = GetMoney()
  if money ~= lastMoney then
    lastMoney = money
    print(GetCoinTextureString(money))
  end
end)
```

## Good

```lua
local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_MONEY")
f:SetScript("OnEvent", function()
  print(GetCoinTextureString(GetMoney()))
end)
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- First Timers `06-notes/addon-dev/api-events-frames.md`
