local function F(t)
  for _, v in ipairs(t) do
    return v
  end
end
print(F({}))
