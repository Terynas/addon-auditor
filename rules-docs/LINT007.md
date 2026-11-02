# LINT007: Suspicious control flow

**Category:** lint

## Why

Unreachable code, loops that always exit on the first pass and empty branches usually mean a condition or `return` is in the wrong place.

## Bad

```lua
local function F(t)
  for _, v in ipairs(t) do
    return v
  end
end
print(F({}))
```

## Good

```lua
local function F(t)
  return t[1]
end
print(F({}))
```

## References

- [luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)
