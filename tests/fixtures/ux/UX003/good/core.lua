local f = CreateFrame("Frame", "FixtureWindow", UIParent, "BasicFrameTemplateWithInset")
f:SetSize(320, 240)
f:SetPoint("CENTER")
f:Hide()
tinsert(UISpecialFrames, "FixtureWindow")

SLASH_FIXTURE1 = "/fixture"
SlashCmdList.FIXTURE = function()
    f:SetShown(not f:IsShown())
end
