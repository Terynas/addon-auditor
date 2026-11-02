local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function()
  FixtureDB = FixtureDB or {}
  FixtureDB.logins = FixtureDB.logins or {}
  table.insert(FixtureDB.logins, { when = time(), zone = GetRealZoneText() })
end)
