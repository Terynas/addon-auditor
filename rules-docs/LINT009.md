# LINT009: .luacheckrc disables global checks

**Category:** lint

## Why

Accidental globals and calls to APIs that do not exist are the most valuable things luacheck finds in WoW code. `global = false`, `allow_defined = true` or ignoring the `11x` codes turns that off for the whole addon. List the globals you really export in `globals = { ... }`.

## Bad

```lua
-- .luacheckrc
std = "lua51"
global = false
```

## Good

```lua
-- .luacheckrc
std = "lua51"
globals = { "MyAddonDB", "SLASH_MYADDON1" }
```

## References

- [luacheck config](https://luacheck.readthedocs.io/en/stable/config.html)
