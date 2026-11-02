# LINT003: Accidental global variable

**Category:** lint

## Why

Every addon shares one global environment. A forgotten `local` leaks state that other addons can overwrite (or that overwrites theirs), and global lookups are slower than locals. Keep exported state on one addon-prefixed namespace table and declare everything else `local`.

## Bad

```lua
local function Count()
  counter = (counter or 0) + 1
  return counter
end
print(Count())
```

## Good

```lua
local counter = 0
local function Count()
  counter = counter + 1
  return counter
end
print(Count())
```

## References

- [luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)
