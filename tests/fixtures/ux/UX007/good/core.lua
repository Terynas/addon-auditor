FixtureDB = FixtureDB or { minimap = { hide = false } }

local btn = CreateFrame("Button", "FixtureMinimapButton", Minimap)
btn:SetSize(32, 32)
btn:SetPoint("CENTER", Minimap, "CENTER", -70, 0)
btn:SetNormalTexture("Interface\\Icons\\INV_Misc_QuestionMark")
btn:SetShown(not FixtureDB.minimap.hide)
