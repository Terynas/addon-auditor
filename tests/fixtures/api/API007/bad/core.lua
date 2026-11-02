local function FullName(unit)
  local name, realm = UnitName(unit)
  return name .. "-" .. (realm or GetNormalizedRealmName())
end
print(FullName("target"))
