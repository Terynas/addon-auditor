# PERF011: Debug message formatted in a hot path

**Category:** perf

## Why

Lua evaluates arguments before the call, so `Debug("aura on " .. unit)` builds a new string every time the hot code runs, even when the debug wrapper checks its flag and throws the string away. In OnUpdate or frequent-event handlers that is pure garbage. Check the flag at the call site, or pass raw values and format inside the debug function after the check.

## Bad

```lua
local ns = { debug = false }
local function Debug(msg)
  if ns.debug then print(msg) end
end

local f = CreateFrame("Frame")
f:RegisterUnitEvent("UNIT_AURA", "player")
f:SetScript("OnEvent", function(self, event, unit)
  Debug("aura update for " .. unit)
end)
```

## Good

```lua
local ns = { debug = false }
local function Debug(msg)
  print(msg)
end

local f = CreateFrame("Frame")
f:RegisterUnitEvent("UNIT_AURA", "player")
f:SetScript("OnEvent", function(self, event, unit)
  if ns.debug then
    Debug("aura update for " .. unit)
  end
end)
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- First Timers `06-notes/addon-dev/debugging-and-taint.md`
