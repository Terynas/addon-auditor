local PREFIX = "MyAddon"
C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)
local f = CreateFrame("Frame")
f:RegisterEvent("CHAT_MSG_ADDON")
f:SetScript("OnEvent", function(self, event, ...)
  local prefix, message, channel, sender = ...
  if prefix ~= PREFIX then return end
  local cmd, value = strsplit(":", message)
  print(cmd, value, sender)
end)
