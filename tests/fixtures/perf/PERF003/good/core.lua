local list = CreateFrame("Frame", nil, UIParent)
local rows = {}

local function RefreshList(items)
  for i, item in ipairs(items) do
    rows[i] = rows[i] or CreateFrame("Button", nil, list)
    local row = rows[i]
    row:SetSize(200, 20)
    row:SetPoint("TOPLEFT", 0, -20 * i)
    row:SetText(item)
    row:Show()
  end
  for i = #items + 1, #rows do
    rows[i]:Hide()
  end
end

list.Refresh = RefreshList
