local bar = CreateFrame("StatusBar", nil, UIParent)
local label = bar:CreateFontString(nil, "OVERLAY", "GameFontNormal")

bar:SetScript("OnUpdate", function(self, elapsed)
  local info = { hp = UnitHealth("player"), max = UnitHealthMax("player") }
  self:SetValue(info.hp / info.max)
  label:SetText(info.hp .. " / " .. info.max)
end)
