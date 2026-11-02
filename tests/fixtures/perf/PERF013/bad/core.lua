local PREFIX = "FixtureSync"
C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)

local function Broadcast(entries)
  for _, entry in ipairs(entries) do
    C_ChatInfo.SendAddonMessage(PREFIX, entry, "PARTY")
  end
end

FixtureBroadcast = Broadcast
