local function DisplayName(unit)
  local first, surname = UnitName(unit)
  if surname and surname ~= "" then
    return first .. " " .. surname
  end
  return first
end
print(DisplayName("target"), UnitGUID("target"))
