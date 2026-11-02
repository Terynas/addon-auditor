local addonName = ...
local anchor = CreateFrame("Frame", "MyAddonAnchor", UIParent)
local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, loaded)
  if loaded ~= addonName then return end
  MyAddonDB = MyAddonDB or {}
  MyAddonDB.anchorName = anchor:GetName()
  MyAddonDB.clickAction = "print"
end)
