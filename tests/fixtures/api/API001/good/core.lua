local function Announce(text)
  if C_ChatInfo and C_ChatInfo.SendMessage then
    C_ChatInfo.SendMessage({ message = text, chatType = "SAY" })
  else
    C_ChatInfo.SendChatMessage(text, "SAY")
  end
end
local CI = C_ChatInfo
local ok = CI.SendMessage and pcall(CI.SendMessage, {})
Announce(tostring(ok))
