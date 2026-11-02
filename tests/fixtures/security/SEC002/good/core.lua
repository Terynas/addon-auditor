hooksecurefunc("SetItemRef", function(link)
  if link:find("^myaddon:") then print("MyAddon link clicked") end
end)
