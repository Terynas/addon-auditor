local function Say(text)
  local lang = GetDefaultLanguage("player")
  C_ChatInfo.SendChatMessage(text, "SAY", lang)
end
Say("hello")
