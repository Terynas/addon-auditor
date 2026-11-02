local f = CreateFrame("Frame")
local function UpdatePlayerHealth()
  print(UnitHealth("player"))
end

f:RegisterUnitEvent("UNIT_HEALTH", "player")
f:SetScript("OnEvent", function(self, event, unit)
  UpdatePlayerHealth()
end)
