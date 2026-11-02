local PREFIX = "FixtureSync"
C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)

local function Broadcast(entries)
  local payload = table.concat(entries, ";")
  C_ChatInfo.SendAddonMessage(PREFIX, payload:sub(1, 255), "PARTY")
end

FixtureBroadcast = Broadcast
