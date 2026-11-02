# PERF001: Unthrottled OnUpdate handler

**Category:** perf

## Why

OnUpdate runs once per rendered frame: 60-240 times per second, on the same UI thread as every other addon and the default UI. A handler without an elapsed-time throttle pays its full cost every frame for as long as the frame is shown, which shows up directly as lower FPS for players with many addons. Throttle with an `elapsed` accumulator, stop it with `SetScript("OnUpdate", nil)` / `Hide()` when idle, or replace it with events or `C_Timer`.

Not reported: handlers that compare an elapsed accumulator or `GetTime()` against a threshold, dirty-flag early returns, handlers that are cleared/hidden somewhere in the file, call-free bodies, and Animation OnUpdate scripts (they only run while the animation plays).

## Bad

```lua
local clock = CreateFrame("Frame", nil, UIParent)
local text = clock:CreateFontString(nil, "OVERLAY", "GameFontNormal")

clock:SetScript("OnUpdate", function(self, elapsed)
  text:SetText(date("%H:%M:%S"))
end)
```

## Good

```lua
local clock = CreateFrame("Frame", nil, UIParent)
local text = clock:CreateFontString(nil, "OVERLAY", "GameFontNormal")

clock:SetScript("OnUpdate", function(self, elapsed)
  self.t = (self.t or 0) + elapsed
  if self.t < 1 then return end
  self.t = 0
  text:SetText(date("%H:%M:%S"))
end)
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- Warcraft Wiki: UIHANDLER OnUpdate
