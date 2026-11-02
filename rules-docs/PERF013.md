# PERF013: Addon message sent per frame / in a loop

**Category:** perf

## Why

Addon messages share a small server-side budget per character: a short burst, then a slow refill. Sending from OnUpdate, a sub-second ticker or a loop over a list exceeds it; the client then silently drops messages (other addons' too) and sustained flooding can disconnect the player. Batch the payload into one message, queue sends and drain a few per second, or use ChatThrottleLib / AceComm which do that for you.

## Bad

```lua
local PREFIX = "FixtureSync"
C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)

local function Broadcast(entries)
  for _, entry in ipairs(entries) do
    C_ChatInfo.SendAddonMessage(PREFIX, entry, "PARTY")
  end
end

FixtureBroadcast = Broadcast
```

## Good

```lua
local PREFIX = "FixtureSync"
C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)

local function Broadcast(entries)
  local payload = table.concat(entries, ";")
  C_ChatInfo.SendAddonMessage(PREFIX, payload:sub(1, 255), "PARTY")
end

FixtureBroadcast = Broadcast
```

## References

- First Timers `06-notes/addon-dev/performance-and-resources.md`
- Warcraft Wiki: C_ChatInfo.SendAddonMessage
