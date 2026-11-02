local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_TARGET_CHANGED")
f:SetScript("OnEvent", function()
  MyAddonDB = MyAddonDB or {}
  MyAddonDB.lastTargetHealth = UnitHealth("target")
end)
