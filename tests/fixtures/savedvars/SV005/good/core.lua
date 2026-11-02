local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function()
  MyAddonCharDB = MyAddonCharDB or {}
  MyAddonCharDB.gold = GetMoney()
  MyAddonDB = MyAddonDB or {}
  local key = UnitName("player") .. "-" .. GetRealmName()
  MyAddonDB[key] = { gold = GetMoney() }
end)
