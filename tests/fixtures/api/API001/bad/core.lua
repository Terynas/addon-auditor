local function Announce(text)
  C_ChatInfo.SendMessage({ message = text, chatType = "SAY" })
end
Announce("hello")
