local origSetItemRef = SetItemRef
SetItemRef = function(link, text, button, chatFrame)
  if link:find("^myaddon:") then return end
  return origSetItemRef(link, text, button, chatFrame)
end
