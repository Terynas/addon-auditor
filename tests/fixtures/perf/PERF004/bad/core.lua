local panel = CreateFrame("Frame", nil, UIParent)

local function UpdatePanel()
  panel:SetAlpha(GetTime() % 1)
end

C_Timer.NewTicker(1, UpdatePanel)
