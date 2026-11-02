local function RecordLoot(itemLink)
  MyAddonDB = MyAddonDB or {}
  MyAddonDB.loot = MyAddonDB.loot or {}
  table.insert(MyAddonDB.loot, itemLink)
end
SLASH_MYADDON1 = "/myaddon"
SlashCmdList.MYADDON = function(msg)
  if msg == "reset" then MyAddonDB = {} end
end
local f = CreateFrame("Frame")
f:RegisterEvent("CHAT_MSG_LOOT")
f:SetScript("OnEvent", function(self, event, text)
  RecordLoot(text)
end)
