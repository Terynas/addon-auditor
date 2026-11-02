local function Label(itemID)
  local name, _, quality = C_Item.GetItemInfo(itemID)
  if not name then
    C_Item.RequestLoadItemDataByID(itemID)
    return nil
  end
  return "[" .. name .. "] q" .. quality
end
print(Label(6948))
