# PERF002: Allocation in a hot path

**Category:** perf

## Why

Every `{}` constructor, `function ... end` closure and `..`/`string.format` result is a new heap object. In an OnUpdate handler (every frame) or a handler for a very frequent event (UNIT_AURA, UNIT_HEALTH, COMBAT_LOG_EVENT_UNFILTERED, SPELL_UPDATE_COOLDOWN ...) that garbage piles up quickly; Lua's incremental collector then runs steps inside your frame time and produces periodic hitches. Reuse scratch tables (`wipe`), define functions once at file scope, and only rebuild strings when the value changes.

Not reported: code behind a throttle, lazy init (`x = x or {}`), once-guards (`if not pending then`), branches that unregister themselves, and branches for infrequent events in a shared OnEvent dispatcher. Strings are reported at info severity.

## Bad

```lua
local bar = CreateFrame("StatusBar", nil, UIParent)
local label = bar:CreateFontString(nil, "OVERLAY", "GameFontNormal")

bar:SetScript("OnUpdate", function(self, elapsed)
  local info = { hp = UnitHealth("player"), max = UnitHealthMax("player") }
  self:SetValue(info.hp / info.max)
  label:SetText(info.hp .. " / " .. info.max)
end)
```

## Good

```lua
local bar = CreateFrame("StatusBar", nil, UIParent)
local label = bar:CreateFontString(nil, "OVERLAY", "GameFontNormal")
local info = {}

bar:SetScript("OnUpdate", function(self, elapsed)
  self.t = (self.t or 0) + elapsed
  if self.t < 0.2 then return end
  self.t = 0
  info.hp, info.max = UnitHealth("player"), UnitHealthMax("player")
  self:SetValue(info.hp / info.max)
  label:SetText(info.hp .. " / " .. info.max)
end)
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- Programming in Lua: Garbage collection
