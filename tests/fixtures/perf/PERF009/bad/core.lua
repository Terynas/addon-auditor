local names = {}
for id = 1, 20000 do
  local name = C_Item.GetItemNameByID(id)
  if name then
    names[id] = name
  end
end
