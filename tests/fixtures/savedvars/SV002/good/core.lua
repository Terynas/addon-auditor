local addonName = ...
local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, loaded)
  if loaded ~= addonName then return end
  MyAddonDB = MyAddonDB or {}
  MyAddonDB.loads = (MyAddonDB.loads or 0) + 1
  self:UnregisterEvent("ADDON_LOADED")
end)
