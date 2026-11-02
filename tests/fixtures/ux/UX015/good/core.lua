local panel = CreateFrame("Frame")
local check = CreateFrame("CheckButton", nil, panel)
check:SetSize(24, 24)
check:SetPoint("TOPLEFT", 16, -16)
check:SetNormalTexture("Interface\\Buttons\\UI-CheckBox-Up")
check:SetPushedTexture("Interface\\Buttons\\UI-CheckBox-Down")
check:SetCheckedTexture("Interface\\Buttons\\UI-CheckBox-Check")

local function LegacyPanel()
    if Settings and Settings.RegisterVerticalLayoutCategory then
        return
    end
    return CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
end
LegacyPanel()
