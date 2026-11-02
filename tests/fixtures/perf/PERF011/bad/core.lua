local ns = { debug = false }
local function Debug(msg)
  if ns.debug then print(msg) end
end

local f = CreateFrame("Frame")
f:RegisterUnitEvent("UNIT_AURA", "player")
f:SetScript("OnEvent", function(self, event, unit)
  Debug("aura update for " .. unit)
end)
