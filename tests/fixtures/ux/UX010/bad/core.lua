print("Fixture loaded. Type /fixture for options.")

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(self, event)
    if event == "PLAYER_LOGIN" then
        print("Fixture ready.")
    end
end)
