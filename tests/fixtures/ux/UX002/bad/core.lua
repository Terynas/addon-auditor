FixtureDB = FixtureDB or {}

SLASH_FIXTURE1 = "/fixture"
SlashCmdList.FIXTURE = function(msg)
    if msg == "reset" then
        FixtureDB = {}
    end
end
