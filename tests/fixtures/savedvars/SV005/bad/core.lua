local addonName = ...
local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function()
  MyAddonCharDB = MyAddonCharDB or {}
  local key = UnitName("player") .. "-" .. GetRealmName()
  MyAddonCharDB[key] = { gold = GetMoney() }
end)
