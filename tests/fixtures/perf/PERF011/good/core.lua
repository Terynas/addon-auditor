local ns = { debug = false }
local function Debug(msg)
  print(msg)
end

local f = CreateFrame("Frame")
f:RegisterUnitEvent("UNIT_AURA", "player")
f:SetScript("OnEvent", function(self, event, unit)
  if ns.debug then
    Debug("aura update for " .. unit)
  end
end)
