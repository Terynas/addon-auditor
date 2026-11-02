local f = CreateFrame("Frame")
local function UpdatePlayerHealth()
  print(UnitHealth("player"))
end

f:RegisterEvent("UNIT_HEALTH")
f:SetScript("OnEvent", function(self, event, unit)
  if unit ~= "player" then return end
  UpdatePlayerHealth()
end)
