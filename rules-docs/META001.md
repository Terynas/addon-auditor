# META001: Suppression without a reason

**Category:** meta

## Why

An `-- auditor:ignore ID` comment hides a finding from every future audit. Without a reason the next agent cannot tell whether it was a deliberate trade-off or a shortcut, and may copy the pattern elsewhere.

## Bad

```lua
-- auditor:ignore PERF001
local x = 1
print(x)
```

## Good

```lua
-- auditor:ignore PERF001 throttled to 0.2s by the caller
local x = 1
print(x)
```

## References

- First Timers `06-notes/addon-dev/`
