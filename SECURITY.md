# Security

addon-auditor only reads addon files and runs `luacheck`; it never executes addon Lua. The MCP server restricts paths to the directories passed in `ADDON_AUDITOR_ROOTS` (or the current working directory).

Report vulnerabilities privately through GitHub Security Advisories on this repository rather than public issues.
