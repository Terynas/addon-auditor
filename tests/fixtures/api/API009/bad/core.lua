local function Label(itemID)
  local name, _, quality = C_Item.GetItemInfo(itemID)
  return "[" .. name .. "] q" .. quality
end
print(Label(6948))
