# LINT001: Lua syntax error

**Category:** lint

## Why

WoW stops loading a file at the first syntax error. Everything defined after it (and often the whole addon, because later files depend on it) is missing, and the user sees a Lua error on login.

## Bad

```lua
local x = = 1
```

## Good

```lua
local x = 1
print(x)
```

## References

- [luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)
