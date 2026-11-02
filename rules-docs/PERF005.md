# PERF005: ADDON_LOADED never unregistered

**Category:** perf

## Why

ADDON_LOADED fires once for every addon that loads, including load-on-demand Blizzard modules opened later in the session (auction house, talents, collections ...). A handler that only waits for its own addon name keeps being dispatched for nothing. Unregister it once your init has run, or use `EventUtil.ContinueOnAddOnLoaded`. PLAYER_LOGIN is not reported: it fires once per session, so leaving it registered costs nothing.

Not reported: handlers that also watch other addons (`IsAddOnLoaded`, comparisons with `Blizzard_*` names) and addons that call `UnregisterAllEvents`.

## Bad

```lua
local addonName = ...
local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, loaded)
  if loaded == addonName then
    FixtureSettings = FixtureSettings or {}
  end
end)
```

## Good

```lua
local addonName = ...
local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, loaded)
  if loaded == addonName then
    FixtureSettings = FixtureSettings or {}
    self:UnregisterEvent("ADDON_LOADED")
  end
end)
```

## References

- First Timers `06-notes/addon-dev/api-events-frames.md`
- First Timers `06-notes/addon-dev/savedvariables-and-load-order.md`
- Warcraft Wiki: ADDON_LOADED
