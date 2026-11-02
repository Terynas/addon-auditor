local bar = CreateFrame("StatusBar", nil, UIParent)
local label = bar:CreateFontString(nil, "OVERLAY", "GameFontNormal")
local info = {}

bar:SetScript("OnUpdate", function(self, elapsed)
  self.t = (self.t or 0) + elapsed
  if self.t < 0.2 then return end
  self.t = 0
  info.hp, info.max = UnitHealth("player"), UnitHealthMax("player")
  self:SetValue(info.hp / info.max)
  label:SetText(info.hp .. " / " .. info.max)
end)
