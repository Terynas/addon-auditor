# LINT006: Shadowed variable

**Category:** lint

## Why

A local that shadows an outer local makes later edits silently touch the wrong variable.

## Bad

```lua
local count = 1
local function F()
  local count = 2
  return count
end
print(count, F())
```

## Good

```lua
local count = 1
local function F()
  local inner = 2
  return inner
end
print(count, F())
```

## References

- [luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)
