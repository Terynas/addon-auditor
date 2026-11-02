local lastMoney
local f = CreateFrame("Frame")
f:SetScript("OnUpdate", function(self, elapsed)
  self.t = (self.t or 0) + elapsed
  if self.t < 0.5 then return end
  self.t = 0
  local money = GetMoney()
  if money ~= lastMoney then
    lastMoney = money
    print(GetCoinTextureString(money))
  end
end)
