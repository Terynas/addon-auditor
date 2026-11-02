local clock = CreateFrame("Frame", nil, UIParent)
local text = clock:CreateFontString(nil, "OVERLAY", "GameFontNormal")

clock:SetScript("OnUpdate", function(self, elapsed)
  text:SetText(date("%H:%M:%S"))
end)
