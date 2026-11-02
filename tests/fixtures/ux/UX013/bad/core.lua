local L = FixtureLocale

local f = CreateFrame("Frame", nil, UIParent)
local title = f:CreateFontString(nil, "OVERLAY", "GameFontNormal")
title:SetText(L["Fixture"])
local hint = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
hint:SetText("Drag items here to add them to the list.")
