local panel = CreateFrame("Frame", nil, UIParent)
local ticker

local function UpdatePanel()
  panel:SetAlpha(GetTime() % 1)
end

panel:SetScript("OnShow", function()
  ticker = C_Timer.NewTicker(1, UpdatePanel)
end)
panel:SetScript("OnHide", function()
  if ticker then
    ticker:Cancel()
    ticker = nil
  end
end)
