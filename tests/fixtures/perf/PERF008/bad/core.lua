local f = CreateFrame("Frame")
local bars = {}

f:RegisterUnitEvent("UNIT_HEALTH", "player")
f:SetScript("OnEvent", function(self, event, unit)
  local pct = UnitHealth(unit) / UnitHealthMax(unit) * 100
  for i = 1, #bars do
    bars[i]:SetValue(math.floor(pct / 10))
  end
end)
