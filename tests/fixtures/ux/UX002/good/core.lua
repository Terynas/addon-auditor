FixtureDB = FixtureDB or {}

SLASH_FIXTURE1 = "/fixture"
SlashCmdList.FIXTURE = function(msg)
    local cmd = (msg or ""):lower():match("^%s*(%S*)")
    if cmd == "reset" then
        FixtureDB = {}
        print("Fixture: reset.")
    else
        print("/fixture reset - clear saved data")
        print("/fixture help - this list")
    end
end
