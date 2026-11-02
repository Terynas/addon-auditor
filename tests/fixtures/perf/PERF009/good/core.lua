local names

local function ItemName(id)
  names = names or {}
  if names[id] == nil then
    names[id] = C_Item.GetItemNameByID(id) or false
  end
  return names[id] or nil
end

FixtureItemName = ItemName
