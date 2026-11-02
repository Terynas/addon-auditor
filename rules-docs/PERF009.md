# PERF009: Heavy loop at file load

**Category:** perf

## Why

File-scope code runs while the loading screen is up, for every login and /reload, before most item/spell data is cached by the client (so data queries often return nil anyway). Iterating thousands of IDs, walking `GetNum*()` collections or creating hundreds of frames there makes every load slower for the user. Defer the work to PLAYER_LOGIN or to first use, spread it with `C_Timer.After`, or create frames on demand from a pool.

Reported only for file-scope loops that call data APIs with a large constant bound (1000+) or a `GetNum*()` bound, or that create frames with a bound of 100+.

## Bad

```lua
local names = {}
for id = 1, 20000 do
  local name = C_Item.GetItemNameByID(id)
  if name then
    names[id] = name
  end
end
```

## Good

```lua
local names

local function ItemName(id)
  names = names or {}
  if names[id] == nil then
    names[id] = C_Item.GetItemNameByID(id) or false
  end
  return names[id] or nil
end

FixtureItemName = ItemName
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- First Timers `06-notes/addon-dev/savedvariables-and-load-order.md`
