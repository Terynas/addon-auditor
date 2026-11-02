local addonName = ...
local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, loaded)
  if loaded == addonName then
    FixtureSettings = FixtureSettings or {}
    self:UnregisterEvent("ADDON_LOADED")
  end
end)
