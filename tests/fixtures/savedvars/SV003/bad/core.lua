local addonName = ...
local defaults = {
  enabled = true,
  scale = 1,
  frame = { x = 0, y = 0, point = "CENTER" },
  colors = { r = 1, g = 1, b = 1 },
}
local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, loaded)
  if loaded ~= addonName then return end
  MyAddonDB = MyAddonDB or CopyTable(defaults)
end)
