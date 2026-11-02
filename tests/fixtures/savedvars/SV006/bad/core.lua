local function RecordLoot(itemLink)
  MyAddonDB = { loot = {} }
  table.insert(MyAddonDB.loot, itemLink)
end
local f = CreateFrame("Frame")
f:RegisterEvent("CHAT_MSG_LOOT")
f:SetScript("OnEvent", function(self, event, text)
  RecordLoot(text)
end)
