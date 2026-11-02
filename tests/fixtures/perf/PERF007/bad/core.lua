local f = CreateFrame("Frame")
f:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")
f:SetScript("OnEvent", function()
  local _, subevent, _, sourceGUID = CombatLogGetCurrentEventInfo()
  if subevent ~= "SPELL_INTERRUPT" or sourceGUID ~= UnitGUID("player") then return end
  print("Interrupted!")
end)
