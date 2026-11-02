local lastReply = {}
local f = CreateFrame("Frame")
f:RegisterEvent("CHAT_MSG_WHISPER")
f:SetScript("OnEvent", function(self, event, text, sender)
  local now = GetTime()
  if lastReply[sender] and now - lastReply[sender] < 60 then return end
  lastReply[sender] = now
  SendChatMessage("I am AFK", "WHISPER", nil, sender)
end)
