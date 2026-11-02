local function Say(text)
  C_ChatInfo.SendChatMessage(text, "SAY", nil)
end
Say("hello")
