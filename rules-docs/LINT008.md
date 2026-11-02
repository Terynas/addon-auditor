# LINT008: Style / formatting

**Category:** lint

## Why

Trailing whitespace and inconsistent indentation are noise in diffs. Low priority; fix while touching the line.

## Bad

```lua
local x = 1   
print(x)
```

## Good

```lua
local x = 1
print(x)
```

## References

- [luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)
