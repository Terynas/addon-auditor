FixtureDB = FixtureDB or {}

local f = CreateFrame("Frame", nil, UIParent)
f:SetSize(200, 100)
f:SetPoint("CENTER")
f:SetMovable(true)
f:SetClampedToScreen(true)
f:EnableMouse(true)
f:RegisterForDrag("LeftButton")
f:SetScript("OnDragStart", f.StartMoving)
f:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    local point, _, relativePoint, x, y = self:GetPoint()
    FixtureDB.position = { point = point, relativePoint = relativePoint, x = x, y = y }
end)
