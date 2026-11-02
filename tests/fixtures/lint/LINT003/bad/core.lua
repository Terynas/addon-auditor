local function Count()
  counter = (counter or 0) + 1
  return counter
end
print(Count())
