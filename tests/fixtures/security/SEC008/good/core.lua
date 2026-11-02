local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_TARGET_CHANGED")
f:SetScript("OnEvent", function()
  MyAddonDB = MyAddonDB or {}
  local hp = UnitHealth("target")
  if not issecretvalue(hp) then
    MyAddonDB.lastTargetHealth = hp
  end
end)
