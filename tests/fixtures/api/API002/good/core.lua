local function Shout(text)
  if C_PartyChat and C_PartyChat.Send then
    C_PartyChat.Send(text)
  else
    C_ChatInfo.SendChatMessage(text, "PARTY")
  end
end
Shout("hi")
