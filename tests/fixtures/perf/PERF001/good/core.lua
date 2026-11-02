local clock = CreateFrame("Frame", nil, UIParent)
local text = clock:CreateFontString(nil, "OVERLAY", "GameFontNormal")

clock:SetScript("OnUpdate", function(self, elapsed)
  self.t = (self.t or 0) + elapsed
  if self.t < 1 then return end
  self.t = 0
  text:SetText(date("%H:%M:%S"))
end)
