local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event)
  MyAddonDB = MyAddonDB or {}
  MyAddonDB.loads = (MyAddonDB.loads or 0) + 1
end)
