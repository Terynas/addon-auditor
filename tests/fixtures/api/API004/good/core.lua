local count = C_Item.GetItemCount(6948)
local Legacy = C_Item and C_Item.GetItemCount or GetItemCount
print(count, Legacy(6948))
