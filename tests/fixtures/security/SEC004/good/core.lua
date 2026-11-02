local btn = CreateFrame("Button", "MyAddonTargetButton", UIParent, "SecureActionButtonTemplate")
btn:SetAttribute("type", "target")
local pending = false
local f = CreateFrame("Frame")
f:RegisterEvent("GROUP_ROSTER_UPDATE")
f:RegisterEvent("PLAYER_REGEN_ENABLED")
f:SetScript("OnEvent", function(self, event)
  if InCombatLockdown() then
    pending = true
    return
  end
  if event == "PLAYER_REGEN_ENABLED" and not pending then return end
  pending = false
  btn:SetAttribute("unit", "party1")
  btn:Show()
end)
