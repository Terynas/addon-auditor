# LINT004: Overwriting a read-only (Blizzard) global

**Category:** lint

## Why

Replacing a client function (`GetItemInfo = ...`, `function ChatFrame_OnHyperlinkShow() ... end`) changes it for every addon and the default UI, and the replacement taints secure code paths that call it, which leads to `ADDON_ACTION_BLOCKED`. Post-hook it instead.

## Bad

```lua
function GetItemInfo(item)
  return nil
end
```

## Good

```lua
hooksecurefunc("GetItemInfo", function(item)
  -- runs after the original
end)
```

## References

- [luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)
- Warcraft Wiki: hooksecurefunc
