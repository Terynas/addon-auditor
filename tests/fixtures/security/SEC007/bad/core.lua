local f = CreateFrame("Frame")
f:RegisterEvent("CHAT_MSG_ADDON")
f:SetScript("OnEvent", function(self, event, ...)
  local prefix, message, channel, sender = ...
  local cmd, value = strsplit(":", message)
  print(cmd, value, sender)
end)
