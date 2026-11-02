local btn = CreateFrame("Button", "MyAddonCastButton", UIParent, "SecureActionButtonTemplate")
btn:RegisterForClicks("AnyDown")
btn:SetAttribute("type", "spell")
btn:SetAttribute("spell", "Frostbolt")
