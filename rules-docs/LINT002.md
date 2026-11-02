# LINT002: Access to an undefined global

**Category:** lint

## Why

A global that neither your addon nor the client defines evaluates to `nil`. Calling it throws `attempt to call a nil value`. Common causes: typos, a missing `local`, or an API invented by an AI assistant or removed in this client. Reads that are existence checks (`if X then`, `X or Y`) are not reported.

## Bad

```lua
local hp = UnitHealthh("player")
print(hp)
```

## Good

```lua
local hp = UnitHealth("player")
print(hp)
```

## References

- [luacheck warnings list](https://luacheck.readthedocs.io/en/stable/warnings.html)
- `addon-auditor api <Name>` to check a symbol per client
