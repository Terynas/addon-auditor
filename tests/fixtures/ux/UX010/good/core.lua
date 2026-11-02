local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(self, event)
    if event == "PLAYER_LOGIN" then
        FixtureDB = FixtureDB or {}
        if not FixtureDB.welcomeSeen then
            print("Fixture: type /fixture for options.")
            FixtureDB.welcomeSeen = true
        end
    end
end)
