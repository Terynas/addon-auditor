# LINT005: Unused variable / value

**Category:** lint

## Why

Unused locals and values are dead code or a sign the wrong variable is used further down.

## Bad

```lua
local function F()
  local unused = 1
  return 2
end
print(F())
```

## Good

```lua
local function F()
  return 2
end
print(F())
```

## References

- [luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)
