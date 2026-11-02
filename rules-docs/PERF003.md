# PERF003: CreateFrame in a repeatedly-run path

**Category:** perf

## Why

Frames, textures and font strings are never garbage collected: once created they live until /reload. Calling `CreateFrame` from an event handler, an OnUpdate/OnShow/OnEnter script or a `Refresh`/`Update` function leaks a new frame (with its regions and scripts) every time it runs, so memory and per-frame layout cost grow for the whole session. Create rows once and reuse them, or use `CreateFramePool` / `CreateObjectPool`.

Not reported: creation behind a cache check (`rows[i] = rows[i] or CreateFrame(...)`, `if not self.frame then`, an early `if self.frame then return end`) and one-shot load events (ADDON_LOADED, PLAYER_LOGIN, PLAYER_ENTERING_WORLD).

## Bad

```lua
local list = CreateFrame("Frame", nil, UIParent)

local function RefreshList(items)
  for i, item in ipairs(items) do
    local row = CreateFrame("Button", nil, list)
    row:SetSize(200, 20)
    row:SetPoint("TOPLEFT", 0, -20 * i)
    row:SetText(item)
  end
end

list.Refresh = RefreshList
```

## Good

```lua
local list = CreateFrame("Frame", nil, UIParent)
local rows = {}

local function RefreshList(items)
  for i, item in ipairs(items) do
    rows[i] = rows[i] or CreateFrame("Button", nil, list)
    local row = rows[i]
    row:SetSize(200, 20)
    row:SetPoint("TOPLEFT", 0, -20 * i)
    row:SetText(item)
    row:Show()
  end
  for i = #items + 1, #rows do
    rows[i]:Hide()
  end
end

list.Refresh = RefreshList
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- Warcraft Wiki: CreateFramePool
