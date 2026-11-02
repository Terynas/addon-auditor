local count = 1
local function F()
  local count = 2
  return count
end
print(count, F())
