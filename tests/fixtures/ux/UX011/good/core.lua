StaticPopupDialogs.FIXTURE_WELCOME = { text = "Welcome to Fixture!", button1 = OKAY }

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(self, event)
    if event == "PLAYER_LOGIN" then
        FixtureDB = FixtureDB or {}
        if not FixtureDB.introSeen then
            StaticPopup_Show("FIXTURE_WELCOME")
            FixtureDB.introSeen = true
        end
    end
end)
