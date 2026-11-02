local addonName, ns = ...
local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, loaded)
  if loaded ~= addonName then return end
  MyAddonDB = MyAddonDB or {}
  if MyAddonDB.scale == nil then MyAddonDB.scale = 1 end
  ns.db = MyAddonDB
  self:UnregisterEvent("ADDON_LOADED")
end)
