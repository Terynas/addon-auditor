local btn = CreateFrame("Button", "MyAddonCastButton", UIParent, "UIPanelButtonTemplate")
btn:SetScript("OnClick", function()
  CastSpellByName("Frostbolt")
end)
