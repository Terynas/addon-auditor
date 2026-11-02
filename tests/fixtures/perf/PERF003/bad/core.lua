local list = CreateFrame("Frame", nil, UIParent)

local function RefreshList(items)
  for i, item in ipairs(items) do
    local row = CreateFrame("Button", nil, list)
    row:SetSize(200, 20)
    row:SetPoint("TOPLEFT", 0, -20 * i)
    row:SetText(item)
  end
end

list.Refresh = RefreshList
