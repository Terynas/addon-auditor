local MAX_LOGINS = 50
local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function()
  FixtureDB = FixtureDB or {}
  FixtureDB.logins = FixtureDB.logins or {}
  table.insert(FixtureDB.logins, { when = time(), zone = GetRealZoneText() })
  while #FixtureDB.logins > MAX_LOGINS do
    table.remove(FixtureDB.logins, 1)
  end
end)
