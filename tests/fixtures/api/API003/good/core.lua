local function Stage()
  if C_Scenario and C_Scenario.GetInfo then
    return C_Scenario.GetInfo()
  end
end
local function Stage2()
  if WOW_PROJECT_ID ~= WOW_PROJECT_MAINLINE then return end
  return C_Scenario.GetInfo()
end
print(Stage(), Stage2())
