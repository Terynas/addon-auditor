local defaults = { scale = 1, locked = false }

FixtureDB = FixtureDB or CopyTable(defaults)

if Settings and Settings.RegisterVerticalLayoutCategory then
    local category = Settings.RegisterVerticalLayoutCategory("Fixture")
    Settings.RegisterAddOnCategory(category)
end
