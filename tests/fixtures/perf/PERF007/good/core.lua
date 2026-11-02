local f = CreateFrame("Frame")
f:RegisterUnitEvent("UNIT_SPELLCAST_SUCCEEDED", "player")
f:SetScript("OnEvent", function(self, event, unit, castGUID, spellID)
  if spellID == 6552 then
    print("Pummel used")
  end
end)
