local PREFIX = "MyAddon"
local handlers = {
  ping = function(arg) print("ping", arg) end,
}
local f = CreateFrame("Frame")
f:RegisterEvent("CHAT_MSG_ADDON")
f:SetScript("OnEvent", function(self, event, prefix, message)
  if prefix ~= PREFIX then return end
  local cmd, arg = message:match("^(%a+):(.*)$")
  local handler = cmd and handlers[cmd]
  if handler then handler(arg) end
end)
