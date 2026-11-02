"""Fixture/doc specs for PERF rules.

Usage: python scripts/new_fixture.py scripts/specs_perf.py [--force]
"""

PERF_NOTE = "First Timers `06-notes/addon-dev/performance-and-resources.md`"
EVENTS_NOTE = "First Timers `06-notes/addon-dev/api-events-frames.md`"
SV_NOTE = "First Timers `06-notes/addon-dev/savedvariables-and-load-order.md`"
SV_TOC = ("## Interface: 16001, 120107\n## Title: Fixture\n## Notes: auditor fixture\n## Version: 1.0\n"
          "## SavedVariables: FixtureDB\n\ncore.lua\n")

SPECS = [
    {
        "id": "PERF001", "category": "perf", "title": "Unthrottled OnUpdate handler",
        "why": "OnUpdate runs once per rendered frame: 60-240 times per second, on the same UI thread as every "
               "other addon and the default UI. A handler without an elapsed-time throttle pays its full cost "
               "every frame for as long as the frame is shown, which shows up directly as lower FPS for "
               "players with many addons. Throttle with an `elapsed` accumulator, stop it with "
               "`SetScript(\"OnUpdate\", nil)` / `Hide()` when idle, or replace it with events or `C_Timer`.\n\n"
               "Not reported: handlers that compare an elapsed accumulator or `GetTime()` against a threshold, "
               "dirty-flag early returns, handlers that are cleared/hidden somewhere in the file, call-free "
               "bodies, and Animation OnUpdate scripts (they only run while the animation plays).",
        "bad": {"core.lua": (
            "local clock = CreateFrame(\"Frame\", nil, UIParent)\n"
            "local text = clock:CreateFontString(nil, \"OVERLAY\", \"GameFontNormal\")\n\n"
            "clock:SetScript(\"OnUpdate\", function(self, elapsed)\n"
            "  text:SetText(date(\"%H:%M:%S\"))\n"
            "end)\n")},
        "good": {"core.lua": (
            "local clock = CreateFrame(\"Frame\", nil, UIParent)\n"
            "local text = clock:CreateFontString(nil, \"OVERLAY\", \"GameFontNormal\")\n\n"
            "clock:SetScript(\"OnUpdate\", function(self, elapsed)\n"
            "  self.t = (self.t or 0) + elapsed\n"
            "  if self.t < 1 then return end\n"
            "  self.t = 0\n"
            "  text:SetText(date(\"%H:%M:%S\"))\n"
            "end)\n")},
        "refs": [PERF_NOTE, "Warcraft Wiki: UIHANDLER OnUpdate"],
    },
    {
        "id": "PERF002", "category": "perf", "title": "Allocation in a hot path",
        "why": "Every `{}` constructor, `function ... end` closure and `..`/`string.format` result is a new heap "
               "object. In an OnUpdate handler (every frame) or a handler for a very frequent event (UNIT_AURA, "
               "UNIT_HEALTH, COMBAT_LOG_EVENT_UNFILTERED, SPELL_UPDATE_COOLDOWN ...) that garbage piles up "
               "quickly; Lua's incremental collector then runs steps inside your frame time and produces "
               "periodic hitches. Reuse scratch tables (`wipe`), define functions once at file scope, and only "
               "rebuild strings when the value changes.\n\n"
               "Not reported: code behind a throttle, lazy init (`x = x or {}`), once-guards "
               "(`if not pending then`), branches that unregister themselves, and branches for infrequent "
               "events in a shared OnEvent dispatcher. Strings are reported at info severity.",
        "bad": {"core.lua": (
            "local bar = CreateFrame(\"StatusBar\", nil, UIParent)\n"
            "local label = bar:CreateFontString(nil, \"OVERLAY\", \"GameFontNormal\")\n\n"
            "bar:SetScript(\"OnUpdate\", function(self, elapsed)\n"
            "  local info = { hp = UnitHealth(\"player\"), max = UnitHealthMax(\"player\") }\n"
            "  self:SetValue(info.hp / info.max)\n"
            "  label:SetText(info.hp .. \" / \" .. info.max)\n"
            "end)\n")},
        "good": {"core.lua": (
            "local bar = CreateFrame(\"StatusBar\", nil, UIParent)\n"
            "local label = bar:CreateFontString(nil, \"OVERLAY\", \"GameFontNormal\")\n"
            "local info = {}\n\n"
            "bar:SetScript(\"OnUpdate\", function(self, elapsed)\n"
            "  self.t = (self.t or 0) + elapsed\n"
            "  if self.t < 0.2 then return end\n"
            "  self.t = 0\n"
            "  info.hp, info.max = UnitHealth(\"player\"), UnitHealthMax(\"player\")\n"
            "  self:SetValue(info.hp / info.max)\n"
            "  label:SetText(info.hp .. \" / \" .. info.max)\n"
            "end)\n")},
        "refs": [PERF_NOTE, "Programming in Lua: Garbage collection"],
    },
    {
        "id": "PERF003", "category": "perf", "title": "CreateFrame in a repeatedly-run path",
        "why": "Frames, textures and font strings are never garbage collected: once created they live until "
               "/reload. Calling `CreateFrame` from an event handler, an OnUpdate/OnShow/OnEnter script or a "
               "`Refresh`/`Update` function leaks a new frame (with its regions and scripts) every time it runs, "
               "so memory and per-frame layout cost grow for the whole session. Create rows once and reuse them, "
               "or use `CreateFramePool` / `CreateObjectPool`.\n\n"
               "Not reported: creation behind a cache check (`rows[i] = rows[i] or CreateFrame(...)`, "
               "`if not self.frame then`, an early `if self.frame then return end`) and one-shot load events "
               "(ADDON_LOADED, PLAYER_LOGIN, PLAYER_ENTERING_WORLD).",
        "bad": {"core.lua": (
            "local list = CreateFrame(\"Frame\", nil, UIParent)\n\n"
            "local function RefreshList(items)\n"
            "  for i, item in ipairs(items) do\n"
            "    local row = CreateFrame(\"Button\", nil, list)\n"
            "    row:SetSize(200, 20)\n"
            "    row:SetPoint(\"TOPLEFT\", 0, -20 * i)\n"
            "    row:SetText(item)\n"
            "  end\n"
            "end\n\n"
            "list.Refresh = RefreshList\n")},
        "good": {"core.lua": (
            "local list = CreateFrame(\"Frame\", nil, UIParent)\n"
            "local rows = {}\n\n"
            "local function RefreshList(items)\n"
            "  for i, item in ipairs(items) do\n"
            "    rows[i] = rows[i] or CreateFrame(\"Button\", nil, list)\n"
            "    local row = rows[i]\n"
            "    row:SetSize(200, 20)\n"
            "    row:SetPoint(\"TOPLEFT\", 0, -20 * i)\n"
            "    row:SetText(item)\n"
            "    row:Show()\n"
            "  end\n"
            "  for i = #items + 1, #rows do\n"
            "    rows[i]:Hide()\n"
            "  end\n"
            "end\n\n"
            "list.Refresh = RefreshList\n")},
        "refs": [PERF_NOTE, "Warcraft Wiki: CreateFramePool"],
    },
    {
        "id": "PERF004", "category": "perf", "title": "Timer that cannot be cancelled / timer scheduled per frame",
        "why": "`C_Timer.NewTicker` keeps calling its callback until `:Cancel()` is called on the handle. If the "
               "handle is discarded (or never cancelled anywhere), the ticker runs for the whole session, even "
               "when the UI it feeds is hidden or the feature is disabled. `C_Timer.After` in a per-frame or "
               "frequent-event path allocates a timer and usually a closure every call and can stack hundreds "
               "of pending callbacks. A discarded `C_Timer.NewTimer` handle is reported at info: use "
               "`C_Timer.After`, which has no handle object.\n\n"
               "Not reported: tickers with an iteration count, tickers whose callback cancels itself, handles "
               "returned or passed on to other code, and `C_Timer.After` behind a pending/once flag.",
        "bad": {"core.lua": (
            "local panel = CreateFrame(\"Frame\", nil, UIParent)\n\n"
            "local function UpdatePanel()\n"
            "  panel:SetAlpha(GetTime() % 1)\n"
            "end\n\n"
            "C_Timer.NewTicker(1, UpdatePanel)\n")},
        "good": {"core.lua": (
            "local panel = CreateFrame(\"Frame\", nil, UIParent)\n"
            "local ticker\n\n"
            "local function UpdatePanel()\n"
            "  panel:SetAlpha(GetTime() % 1)\n"
            "end\n\n"
            "panel:SetScript(\"OnShow\", function()\n"
            "  ticker = C_Timer.NewTicker(1, UpdatePanel)\n"
            "end)\n"
            "panel:SetScript(\"OnHide\", function()\n"
            "  if ticker then\n"
            "    ticker:Cancel()\n"
            "    ticker = nil\n"
            "  end\n"
            "end)\n")},
        "refs": [PERF_NOTE, "Warcraft Wiki: C_Timer.NewTicker"],
    },
    {
        "id": "PERF005", "category": "perf", "title": "ADDON_LOADED never unregistered",
        "why": "ADDON_LOADED fires once for every addon that loads, including load-on-demand Blizzard modules "
               "opened later in the session (auction house, talents, collections ...). A handler that only "
               "waits for its own addon name keeps being dispatched for nothing. Unregister it once your init "
               "has run, or use `EventUtil.ContinueOnAddOnLoaded`. PLAYER_LOGIN is not reported: it fires once "
               "per session, so leaving it registered costs nothing.\n\n"
               "Not reported: handlers that also watch other addons (`IsAddOnLoaded`, comparisons with "
               "`Blizzard_*` names) and addons that call `UnregisterAllEvents`.",
        "bad": {"core.lua": (
            "local addonName = ...\n"
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterEvent(\"ADDON_LOADED\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, loaded)\n"
            "  if loaded == addonName then\n"
            "    FixtureSettings = FixtureSettings or {}\n"
            "  end\n"
            "end)\n")},
        "good": {"core.lua": (
            "local addonName = ...\n"
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterEvent(\"ADDON_LOADED\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, loaded)\n"
            "  if loaded == addonName then\n"
            "    FixtureSettings = FixtureSettings or {}\n"
            "    self:UnregisterEvent(\"ADDON_LOADED\")\n"
            "  end\n"
            "end)\n")},
        "refs": [EVENTS_NOTE, SV_NOTE, "Warcraft Wiki: ADDON_LOADED"],
    },
    {
        "id": "PERF006", "category": "perf", "title": "UNIT_* event filtered in Lua instead of RegisterUnitEvent",
        "why": "`RegisterEvent(\"UNIT_HEALTH\")` delivers the event for every unit the client tracks: party and "
               "raid members, pets, targets of targets, every nameplate. In a raid that is dozens of Lua calls "
               "per second that immediately `return` because the unit is not `player`. "
               "`RegisterUnitEvent(event, unit1[, unit2])` filters in C, so Lua only wakes for the units you "
               "care about.\n\n"
               "Reported only when every handler for the event starts with a fixed-unit guard "
               "(`if unit ~= \"player\" then return end`) or handles it only in `event == X and unit == \"u\"` "
               "branches, for at most two units (the RegisterUnitEvent limit). Skipped for AceEvent addons.",
        "bad": {"core.lua": (
            "local f = CreateFrame(\"Frame\")\n"
            "local function UpdatePlayerHealth()\n"
            "  print(UnitHealth(\"player\"))\n"
            "end\n\n"
            "f:RegisterEvent(\"UNIT_HEALTH\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, unit)\n"
            "  if unit ~= \"player\" then return end\n"
            "  UpdatePlayerHealth()\n"
            "end)\n")},
        "good": {"core.lua": (
            "local f = CreateFrame(\"Frame\")\n"
            "local function UpdatePlayerHealth()\n"
            "  print(UnitHealth(\"player\"))\n"
            "end\n\n"
            "f:RegisterUnitEvent(\"UNIT_HEALTH\", \"player\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, unit)\n"
            "  UpdatePlayerHealth()\n"
            "end)\n")},
        "refs": [PERF_NOTE, EVENTS_NOTE, "Warcraft Wiki: Frame:RegisterUnitEvent"],
    },
    {
        "id": "PERF007", "category": "perf", "title": "COMBAT_LOG_EVENT_UNFILTERED handler",
        "why": "CLEU fires for every combat-log line within range: every hit, heal, aura application and "
               "periodic tick from every combatant. That is thousands of events per minute in a raid, so any "
               "work done before the subevent filter, and any allocation, is multiplied by that rate. Read "
               "`CombatLogGetCurrentEventInfo()` once, return immediately for subevents/GUIDs you do not need, "
               "and unregister outside the content that needs it. On clients where CLEU is restricted the API "
               "pack reports the registration instead (findings are deduplicated).",
        "bad": {"core.lua": (
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterEvent(\"COMBAT_LOG_EVENT_UNFILTERED\")\n"
            "f:SetScript(\"OnEvent\", function()\n"
            "  local _, subevent, _, sourceGUID = CombatLogGetCurrentEventInfo()\n"
            "  if subevent ~= \"SPELL_INTERRUPT\" or sourceGUID ~= UnitGUID(\"player\") then return end\n"
            "  print(\"Interrupted!\")\n"
            "end)\n")},
        "good": {"core.lua": (
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterUnitEvent(\"UNIT_SPELLCAST_SUCCEEDED\", \"player\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, unit, castGUID, spellID)\n"
            "  if spellID == 6552 then\n"
            "    print(\"Pummel used\")\n"
            "  end\n"
            "end)\n")},
        "refs": [PERF_NOTE, "First Timers `06-notes/addon-dev/midnight-12.md`",
                 "Warcraft Wiki: COMBAT_LOG_EVENT"],
    },
    {
        "id": "PERF008", "category": "perf", "title": "Repeated global lookups in a hot path",
        "why": "A global access (`UnitHealth`, `math.floor`) is a hash lookup in `_G` (plus one per `.` field) "
               "on every execution; a local or upvalue is an indexed slot read. The difference is tiny once but "
               "adds up in code that runs every frame or per frequent event, especially inside loops. Cache "
               "the APIs you use there in file-scope locals: `local floor, UnitHealth = math.floor, UnitHealth`. "
               "Reported at info/low confidence: it is a micro-optimisation, worth doing only in hot paths, "
               "which is the only place this rule looks.",
        "bad": {"core.lua": (
            "local f = CreateFrame(\"Frame\")\n"
            "local bars = {}\n\n"
            "f:RegisterUnitEvent(\"UNIT_HEALTH\", \"player\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, unit)\n"
            "  local pct = UnitHealth(unit) / UnitHealthMax(unit) * 100\n"
            "  for i = 1, #bars do\n"
            "    bars[i]:SetValue(math.floor(pct / 10))\n"
            "  end\n"
            "end)\n")},
        "good": {"core.lua": (
            "local floor = math.floor\n"
            "local UnitHealth, UnitHealthMax = UnitHealth, UnitHealthMax\n"
            "local f = CreateFrame(\"Frame\")\n"
            "local bars = {}\n\n"
            "f:RegisterUnitEvent(\"UNIT_HEALTH\", \"player\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, unit)\n"
            "  local pct = UnitHealth(unit) / UnitHealthMax(unit) * 100\n"
            "  for i = 1, #bars do\n"
            "    bars[i]:SetValue(floor(pct / 10))\n"
            "  end\n"
            "end)\n")},
        "refs": [PERF_NOTE, "Lua Performance Tips (Roberto Ierusalimschy), section on locals"],
    },
    {
        "id": "PERF009", "category": "perf", "title": "Heavy loop at file load",
        "why": "File-scope code runs while the loading screen is up, for every login and /reload, before most "
               "item/spell data is cached by the client (so data queries often return nil anyway). Iterating "
               "thousands of IDs, walking `GetNum*()` collections or creating hundreds of frames there makes "
               "every load slower for the user. Defer the work to PLAYER_LOGIN or to first use, spread it "
               "with `C_Timer.After`, or create frames on demand from a pool.\n\n"
               "Reported only for file-scope loops that call data APIs with a large constant bound (1000+) or "
               "a `GetNum*()` bound, or that create frames with a bound of 100+.",
        "bad": {"core.lua": (
            "local names = {}\n"
            "for id = 1, 20000 do\n"
            "  local name = C_Item.GetItemNameByID(id)\n"
            "  if name then\n"
            "    names[id] = name\n"
            "  end\n"
            "end\n")},
        "good": {"core.lua": (
            "local names\n\n"
            "local function ItemName(id)\n"
            "  names = names or {}\n"
            "  if names[id] == nil then\n"
            "    names[id] = C_Item.GetItemNameByID(id) or false\n"
            "  end\n"
            "  return names[id] or nil\n"
            "end\n\n"
            "FixtureItemName = ItemName\n")},
        "refs": [PERF_NOTE, SV_NOTE],
    },
    {
        "id": "PERF010", "category": "perf", "title": "SavedVariables list grows without bound",
        "why": "SavedVariables are executed as Lua at login and serialized at logout. A list that gets a new "
               "entry every session (or every event) and is never trimmed makes every login, logout and "
               "/reload slower forever and keeps the whole history in memory. Cap lists after inserting "
               "(`while #t > N do table.remove(t, 1) end`) or prune old entries at login.\n\n"
               "Recognises SavedVariables names from the TOC and aliases such as `ns.db = MyDB` / "
               "`local db = MyDB`. Any `table.remove`, `wipe`, `#t > N` check, reset to `{}` or `t[k] = nil` on "
               "the same list anywhere in the addon counts as trimming; inserts guarded by a dedupe check "
               "(`if not seen[x]`, `tContains`) are skipped.",
        "bad": {"TOC": SV_TOC, "core.lua": (
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterEvent(\"PLAYER_LOGIN\")\n"
            "f:SetScript(\"OnEvent\", function()\n"
            "  FixtureDB = FixtureDB or {}\n"
            "  FixtureDB.logins = FixtureDB.logins or {}\n"
            "  table.insert(FixtureDB.logins, { when = time(), zone = GetRealZoneText() })\n"
            "end)\n")},
        "good": {"TOC": SV_TOC, "core.lua": (
            "local MAX_LOGINS = 50\n"
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterEvent(\"PLAYER_LOGIN\")\n"
            "f:SetScript(\"OnEvent\", function()\n"
            "  FixtureDB = FixtureDB or {}\n"
            "  FixtureDB.logins = FixtureDB.logins or {}\n"
            "  table.insert(FixtureDB.logins, { when = time(), zone = GetRealZoneText() })\n"
            "  while #FixtureDB.logins > MAX_LOGINS do\n"
            "    table.remove(FixtureDB.logins, 1)\n"
            "  end\n"
            "end)\n")},
        "refs": [SV_NOTE, PERF_NOTE],
    },
    {
        "id": "PERF011", "category": "perf", "title": "Debug message formatted in a hot path",
        "why": "Lua evaluates arguments before the call, so `Debug(\"aura on \" .. unit)` builds a new string "
               "every time the hot code runs, even when the debug wrapper checks its flag and throws the string "
               "away. In OnUpdate or frequent-event handlers that is pure garbage. Check the flag at the call "
               "site, or pass raw values and format inside the debug function after the check.",
        "bad": {"core.lua": (
            "local ns = { debug = false }\n"
            "local function Debug(msg)\n"
            "  if ns.debug then print(msg) end\n"
            "end\n\n"
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterUnitEvent(\"UNIT_AURA\", \"player\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, unit)\n"
            "  Debug(\"aura update for \" .. unit)\n"
            "end)\n")},
        "good": {"core.lua": (
            "local ns = { debug = false }\n"
            "local function Debug(msg)\n"
            "  print(msg)\n"
            "end\n\n"
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterUnitEvent(\"UNIT_AURA\", \"player\")\n"
            "f:SetScript(\"OnEvent\", function(self, event, unit)\n"
            "  if ns.debug then\n"
            "    Debug(\"aura update for \" .. unit)\n"
            "  end\n"
            "end)\n")},
        "refs": [PERF_NOTE, "First Timers `06-notes/addon-dev/debugging-and-taint.md`"],
    },
    {
        "id": "PERF012", "category": "perf", "title": "Polling state that has an event",
        "why": "Re-reading a value (`GetMoney()`, `UnitHealth()`, zone text, group size ...) from OnUpdate or a "
               "ticker and comparing it with a cached copy costs a C call and a comparison every tick, even "
               "though nothing changed for minutes. The client already announces those changes with events "
               "(PLAYER_MONEY, UNIT_HEALTH, ZONE_CHANGED_NEW_AREA, GROUP_ROSTER_UPDATE ...): register the event "
               "and update from its handler. Low confidence: some UIs poll on purpose for smooth animation.",
        "bad": {"core.lua": (
            "local lastMoney\n"
            "local f = CreateFrame(\"Frame\")\n"
            "f:SetScript(\"OnUpdate\", function(self, elapsed)\n"
            "  self.t = (self.t or 0) + elapsed\n"
            "  if self.t < 0.5 then return end\n"
            "  self.t = 0\n"
            "  local money = GetMoney()\n"
            "  if money ~= lastMoney then\n"
            "    lastMoney = money\n"
            "    print(GetCoinTextureString(money))\n"
            "  end\n"
            "end)\n")},
        "good": {"core.lua": (
            "local f = CreateFrame(\"Frame\")\n"
            "f:RegisterEvent(\"PLAYER_MONEY\")\n"
            "f:SetScript(\"OnEvent\", function()\n"
            "  print(GetCoinTextureString(GetMoney()))\n"
            "end)\n")},
        "refs": [PERF_NOTE, EVENTS_NOTE],
    },
    {
        "id": "PERF013", "category": "perf", "title": "Addon message sent per frame / in a loop",
        "why": "Addon messages share a small server-side budget per character: a short burst, then a slow "
               "refill. Sending from OnUpdate, a sub-second ticker or a loop over a list exceeds it; the client "
               "then silently drops messages (other addons' too) and sustained flooding can disconnect the "
               "player. Batch the payload into one message, queue sends and drain a few per second, or use "
               "ChatThrottleLib / AceComm which do that for you.",
        "bad": {"core.lua": (
            "local PREFIX = \"FixtureSync\"\n"
            "C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)\n\n"
            "local function Broadcast(entries)\n"
            "  for _, entry in ipairs(entries) do\n"
            "    C_ChatInfo.SendAddonMessage(PREFIX, entry, \"PARTY\")\n"
            "  end\n"
            "end\n\n"
            "FixtureBroadcast = Broadcast\n")},
        "good": {"core.lua": (
            "local PREFIX = \"FixtureSync\"\n"
            "C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)\n\n"
            "local function Broadcast(entries)\n"
            "  local payload = table.concat(entries, \";\")\n"
            "  C_ChatInfo.SendAddonMessage(PREFIX, payload:sub(1, 255), \"PARTY\")\n"
            "end\n\n"
            "FixtureBroadcast = Broadcast\n")},
        "refs": [PERF_NOTE, "Warcraft Wiki: C_ChatInfo.SendAddonMessage"],
    },
]
