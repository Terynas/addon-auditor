# PERF004: Timer that cannot be cancelled / timer scheduled per frame

**Category:** perf

## Why

`C_Timer.NewTicker` keeps calling its callback until `:Cancel()` is called on the handle. If the handle is discarded (or never cancelled anywhere), the ticker runs for the whole session, even when the UI it feeds is hidden or the feature is disabled. `C_Timer.After` in a per-frame or frequent-event path allocates a timer and usually a closure every call and can stack hundreds of pending callbacks. A discarded `C_Timer.NewTimer` handle is reported at info: use `C_Timer.After`, which has no handle object.

Not reported: tickers with an iteration count, tickers whose callback cancels itself, handles returned or passed on to other code, and `C_Timer.After` behind a pending/once flag.

## Bad

```lua
local panel = CreateFrame("Frame", nil, UIParent)

local function UpdatePanel()
  panel:SetAlpha(GetTime() % 1)
end

C_Timer.NewTicker(1, UpdatePanel)
```

## Good

```lua
local panel = CreateFrame("Frame", nil, UIParent)
local ticker

local function UpdatePanel()
  panel:SetAlpha(GetTime() % 1)
end

panel:SetScript("OnShow", function()
  ticker = C_Timer.NewTicker(1, UpdatePanel)
end)
panel:SetScript("OnHide", function()
  if ticker then
    ticker:Cancel()
    ticker = nil
  end
end)
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- Warcraft Wiki: C_Timer.NewTicker
