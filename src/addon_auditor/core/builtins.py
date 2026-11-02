"""Globals that exist in every WoW client regardless of API data: Lua 5.1 stdlib + WoW Lua extensions."""

LUA_GLOBALS = frozenset({
    "_G", "_VERSION", "assert", "collectgarbage", "error", "getfenv", "getmetatable", "ipairs", "load",
    "loadstring", "next", "pairs", "pcall", "print", "rawequal", "rawget", "rawset", "select", "setfenv",
    "setmetatable", "tonumber", "tostring", "type", "unpack", "xpcall", "coroutine", "math", "string",
    "table", "bit", "gcinfo", "newproxy",
})

# Aliases and helpers the WoW client injects into the global environment.
WOW_LUA_EXTENSIONS = frozenset({
    "strsplit", "strjoin", "strconcat", "strtrim", "strrev", "strlenutf8", "strcmputf8i", "strsub", "strlen",
    "strlower", "strupper", "strfind", "strmatch", "strrep", "strbyte", "strchar", "gsub", "gmatch", "format",
    "tinsert", "tremove", "tContains", "wipe", "sort", "tostringall", "securecall", "securecallfunction",
    "secureexecuterange", "issecure", "issecurevariable", "hooksecurefunc", "forceinsecure", "debugstack",
    "debugprofilestart", "debugprofilestop", "geterrorhandler", "seterrorhandler", "abs", "ceil", "floor",
    "max", "min", "mod", "sqrt", "random", "fastrandom", "exp", "log", "log10", "frexp", "ldexp", "deg", "rad",
    "cos", "sin", "tan", "acos", "asin", "atan", "atan2", "getn", "foreach", "foreachi", "date", "time",
    "difftime", "scrub", "issecretvalue", "canaccessvalue", "scrubsecretvalues", "issecrettable",
    "canaccesstable", "dumpdeferred", "Mixin", "CreateFromMixins",
})

ALWAYS_KNOWN = LUA_GLOBALS | WOW_LUA_EXTENSIONS
