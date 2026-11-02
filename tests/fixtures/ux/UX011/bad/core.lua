StaticPopupDialogs.FIXTURE_WELCOME = { text = "Welcome to Fixture!", button1 = OKAY }

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(self, event)
    if event == "PLAYER_LOGIN" then
        StaticPopup_Show("FIXTURE_WELCOME")
    end
end)
