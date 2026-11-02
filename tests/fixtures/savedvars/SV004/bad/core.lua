local addonName = ...
local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, loaded)
  if loaded ~= addonName then return end
  MyAddonDB = MyAddonDB or {}
  MyAddonDB.anchor = CreateFrame("Frame", nil, UIParent)
  MyAddonDB.onClick = function() print("clicked") end
end)
