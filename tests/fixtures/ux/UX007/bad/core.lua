FixtureDB = FixtureDB or {}

local btn = CreateFrame("Button", "FixtureMinimapButton", Minimap)
btn:SetSize(32, 32)
btn:SetPoint("CENTER", Minimap, "CENTER", -70, 0)
btn:SetNormalTexture("Interface\\Icons\\INV_Misc_QuestionMark")
