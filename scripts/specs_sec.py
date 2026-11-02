"""Fixture/doc specs for SECURITY (SEC*) and SAVEDVARIABLES (SV*) rules.

Usage: python scripts/new_fixture.py scripts/specs_sec.py [--force]
"""

NOTES = "First Timers `06-notes/addon-dev/"
SEC_NOTE = f"{NOTES}security-and-trust.md`"
TAINT_NOTE = f"{NOTES}debugging-and-taint.md` (Hook safely, ADDON_ACTION_FORBIDDEN)"
UI_NOTE = f"{NOTES}ui-and-secure-templates.md` (Combat lockdown, Secure templates)"
SV_NOTE = f"{NOTES}savedvariables-and-load-order.md`"
MIDNIGHT_NOTE = f"{NOTES}midnight-12.md` (Secret Values)"
EVENTS_NOTE = f"{NOTES}api-events-frames.md` (addon messages)"
WIKI_TAINT = "[Secure Execution and Tainting](https://warcraft.wiki.gg/wiki/Secure_Execution_and_Tainting)"
WIKI_SV = "[Saving variables between game sessions](https://warcraft.wiki.gg/wiki/Saving_variables_between_game_sessions)"
WIKI_HOOK = "[hooksecurefunc](https://warcraft.wiki.gg/wiki/API_hooksecurefunc)"


def toc(sv: str | None = None, per_char: str | None = None, title: str = "MyAddon") -> str:
    out = f"## Interface: 16001, 120107\n## Title: {title}\n## Notes: auditor fixture\n## Version: 1.0\n"
    if sv:
        out += f"## SavedVariables: {sv}\n"
    if per_char:
        out += f"## SavedVariablesPerCharacter: {per_char}\n"
    return out + "\ncore.lua\n"


SV_TOC = toc("MyAddonDB")

SPECS = [
    # ------------------------------------------------------------------ SECURITY
    {
        "id": "SEC001", "category": "security", "title": "Dynamic code execution (loadstring / RunScript)",
        "why": "`loadstring`, `load` and `RunScript` compile a string and run it with the player's full UI "
               "privileges. If any part of that string comes from an addon message, chat, an EditBox or "
               "SavedVariables (which other tools and shared profiles can edit), whoever shapes the string runs "
               "arbitrary Lua: sending mail, deleting items, spamming chat. Parse data into plain values instead. "
               "Severity is `error` for non-constant input (confidence `high` when the source is visibly untrusted) "
               "and `info` for a constant string, which is merely pointless.",
        "bad": {"TOC": toc(), "core.lua":
                "local PREFIX = \"MyAddon\"\nlocal f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"CHAT_MSG_ADDON\")\n"
                "f:SetScript(\"OnEvent\", function(self, event, prefix, message)\n"
                "  if prefix ~= PREFIX then return end\n  local fn = loadstring(message)\n  if fn then fn() end\nend)\n"},
        "good": {"TOC": toc(), "core.lua":
                 "local PREFIX = \"MyAddon\"\nlocal handlers = {\n  ping = function(arg) print(\"ping\", arg) end,\n}\n"
                 "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"CHAT_MSG_ADDON\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event, prefix, message)\n"
                 "  if prefix ~= PREFIX then return end\n"
                 "  local cmd, arg = message:match(\"^(%a+):(.*)$\")\n"
                 "  local handler = cmd and handlers[cmd]\n  if handler then handler(arg) end\nend)\n"},
        "refs": [SEC_NOTE + " (rule 1: never execute data as code)", WIKI_TAINT],
    },
    {
        "id": "SEC002", "category": "security", "title": "Replacing a Blizzard function or global",
        "why": "Assigning over a client API or FrameXML function (`SetItemRef = ...`, `_G.ChatFrame_OnEvent = ...`, "
               "`function GameTooltip:SetUnit() ... end`) replaces it for the default UI and every addon. Secure "
               "Blizzard code that calls it now runs tainted addon code, which surfaces later as "
               "`ADDON_ACTION_BLOCKED` / \"Interface action failed because of an AddOn\" far from the real cause. "
               "`hooksecurefunc` runs your code after the original without replacing it. Polyfills guarded by "
               "`if not X then` or `X = X or ...` are not reported. Overlaps luacheck W121/W122 (LINT004); this "
               "finding wins the dedupe.",
        "bad": {"TOC": toc(), "core.lua":
                "local origSetItemRef = SetItemRef\nSetItemRef = function(link, text, button, chatFrame)\n"
                "  if link:find(\"^myaddon:\") then return end\n"
                "  return origSetItemRef(link, text, button, chatFrame)\nend\n"},
        "good": {"TOC": toc(), "core.lua":
                 "hooksecurefunc(\"SetItemRef\", function(link)\n"
                 "  if link:find(\"^myaddon:\") then print(\"MyAddon link clicked\") end\nend)\n"},
        "refs": [SEC_NOTE + " (rule 2)", TAINT_NOTE, WIKI_HOOK, WIKI_TAINT],
    },
    {
        "id": "SEC003", "category": "security", "title": "SetScript on a Blizzard frame",
        "why": "`GameTooltip:SetScript(\"OnShow\", fn)` removes the handler Blizzard installed (and whatever other "
               "addons hooked), so the default behaviour silently stops and the frame's script is tainted. "
               "`HookScript` chains your function after the existing one. Frames the addon created itself "
               "(`CreateFrame(..., \"MyAddonFrame\")`, XML `name=`) are not reported.",
        "bad": {"TOC": toc(), "core.lua":
                "GameTooltip:SetScript(\"OnShow\", function(self)\n  self:AddLine(\"MyAddon was here\")\nend)\n"},
        "good": {"TOC": toc(), "core.lua":
                 "GameTooltip:HookScript(\"OnShow\", function(self)\n  self:AddLine(\"MyAddon was here\")\nend)\n"
                 "local own = CreateFrame(\"Frame\", \"MyAddonFrame\", UIParent)\n"
                 "own:SetScript(\"OnShow\", function() end)\n"},
        "refs": [TAINT_NOTE, SEC_NOTE + " (rule 2)", WIKI_TAINT],
    },
    {
        "id": "SEC004", "category": "security", "title": "Combat-locked operation without InCombatLockdown() check",
        "why": "Frames built from `SecureActionButtonTemplate` / `Secure*Template` / `SecureHandler*` cannot be "
               "shown, hidden, moved, resized, re-parented or have attributes set while in combat, and "
               "`RegisterStateDriver`, `SetBinding*`, `SetOverrideBinding*` and `ClearOverrideBindings` are locked "
               "too. Event handlers such as `GROUP_ROSTER_UPDATE` fire mid-combat, so the call is blocked and the "
               "addon is blamed. Handlers for login and `PLAYER_REGEN_*` events, and calls behind an "
               "`InCombatLockdown()` check, are not reported. Defer with `PLAYER_REGEN_ENABLED`.",
        "bad": {"TOC": toc(), "core.lua":
                "local btn = CreateFrame(\"Button\", \"MyAddonTargetButton\", UIParent, \"SecureActionButtonTemplate\")\n"
                "btn:SetAttribute(\"type\", \"target\")\n"
                "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"GROUP_ROSTER_UPDATE\")\n"
                "f:SetScript(\"OnEvent\", function()\n  btn:SetAttribute(\"unit\", \"party1\")\n  btn:Show()\nend)\n"},
        "good": {"TOC": toc(), "core.lua":
                 "local btn = CreateFrame(\"Button\", \"MyAddonTargetButton\", UIParent, \"SecureActionButtonTemplate\")\n"
                 "btn:SetAttribute(\"type\", \"target\")\nlocal pending = false\n"
                 "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"GROUP_ROSTER_UPDATE\")\n"
                 "f:RegisterEvent(\"PLAYER_REGEN_ENABLED\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event)\n"
                 "  if InCombatLockdown() then\n    pending = true\n    return\n  end\n"
                 "  if event == \"PLAYER_REGEN_ENABLED\" and not pending then return end\n"
                 "  pending = false\n  btn:SetAttribute(\"unit\", \"party1\")\n  btn:Show()\nend)\n"},
        "refs": [UI_NOTE, TAINT_NOTE, SEC_NOTE + " (rules 2 and 6)"],
    },
    {
        "id": "SEC005", "category": "security", "title": "Generic or colliding global name",
        "why": "All addons share one global table. A global called `db`, `L`, `frame` or `Config`, or a frame "
               "named `MainFrame`, is overwritten by the next addon that picks the same name (or overwrites "
               "theirs); a frame named like a Blizzard one (`PlayerFrame`, `GameTooltip`) replaces the default "
               "UI's object and is an `error`. SavedVariables, `SLASH_*`, `BINDING_*` and additions to "
               "`SlashCmdList` / `StaticPopupDialogs` / `UISpecialFrames` are exempt. Names prefixed with the "
               "addon's name, TOC title, their initials, or the addon's own namespace table are fine. Other "
               "unprefixed Lua globals are reported by LINT003 instead.",
        "bad": {"TOC": toc(), "core.lua":
                "db = {}\nlocal main = CreateFrame(\"Frame\", \"MainFrame\", UIParent)\nmain:Hide()\nprint(db)\n"},
        "good": {"TOC": toc(), "core.lua":
                 "local _, ns = ...\nns.db = {}\n"
                 "local main = CreateFrame(\"Frame\", \"MyAddonMainFrame\", UIParent)\nmain:Hide()\nprint(ns.db)\n"},
        "refs": [SEC_NOTE + " (rule 6, AI checklist)", f"{NOTES}luacheck-and-code-quality.md`"],
    },
    {
        "id": "SEC006", "category": "security", "title": "Unthrottled automatic chat message",
        "why": "`SendChatMessage` inside an event handler or OnUpdate sends once per trigger. Auto-replies to "
               "whispers, loot or roster announcements without a rate limit flood channels, get the player "
               "reported or muted, and can disconnect them for spamming; two such addons can even ping-pong. "
               "On Mainline, SAY/YELL/CHANNEL sends outside instances also need a hardware event. Handlers whose "
               "function compares against `GetTime()`/`time()` (or uses an obvious throttle variable) are not "
               "reported.",
        "bad": {"TOC": toc(), "core.lua":
                "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"CHAT_MSG_WHISPER\")\n"
                "f:SetScript(\"OnEvent\", function(self, event, text, sender)\n"
                "  SendChatMessage(\"I am AFK\", \"WHISPER\", nil, sender)\nend)\n"},
        "good": {"TOC": toc(), "core.lua":
                 "local lastReply = {}\nlocal f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"CHAT_MSG_WHISPER\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event, text, sender)\n  local now = GetTime()\n"
                 "  if lastReply[sender] and now - lastReply[sender] < 60 then return end\n"
                 "  lastReply[sender] = now\n  SendChatMessage(\"I am AFK\", \"WHISPER\", nil, sender)\nend)\n"},
        "refs": [SEC_NOTE + " (rule 4)", EVENTS_NOTE],
    },
    {
        "id": "SEC007", "category": "security", "title": "CHAT_MSG_ADDON payload used without checking the prefix",
        "why": "`CHAT_MSG_ADDON` fires for every prefix registered by any addon on this client, from any sender. A "
               "handler that splits and acts on the payload before comparing its own prefix processes other "
               "addons' traffic or crafted messages. Check the prefix first, then validate version and fields. "
               "Payloads passed to `loadstring`/`RunScript` are reported as errors by SEC001.",
        "bad": {"TOC": toc(), "core.lua":
                "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"CHAT_MSG_ADDON\")\n"
                "f:SetScript(\"OnEvent\", function(self, event, ...)\n"
                "  local prefix, message, channel, sender = ...\n"
                "  local cmd, value = strsplit(\":\", message)\n  print(cmd, value, sender)\nend)\n"},
        "good": {"TOC": toc(), "core.lua":
                 "local PREFIX = \"MyAddon\"\nC_ChatInfo.RegisterAddonMessagePrefix(PREFIX)\n"
                 "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"CHAT_MSG_ADDON\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event, ...)\n"
                 "  local prefix, message, channel, sender = ...\n  if prefix ~= PREFIX then return end\n"
                 "  local cmd, value = strsplit(\":\", message)\n  print(cmd, value, sender)\nend)\n"},
        "refs": [SEC_NOTE + " (rules 1 and 4)", EVENTS_NOTE],
    },
    {
        "id": "SEC008", "category": "security", "title": "Possibly secret value stored in SavedVariables",
        "why": "On Midnight (12.x) and Forever, combat-sensitive values such as another unit's health, power, "
               "level or aura data can be *secret values*. They do not serialize (they save as nil) and any "
               "comparison or arithmetic on them taints the addon for the session. The notes list `UnitHealth`, "
               "`UnitLevel`, `UnitReaction` and `UnitAura`-style results as the main sources; values for the "
               "`\"player\"` unit are not reported. Scrub with `tonumber`/`scrubsecretvalues` or skip when "
               "`issecretvalue(v)`. Low confidence: exact secret rules vary by patch, verify in-game.",
        "bad": {"TOC": SV_TOC, "core.lua":
                "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"PLAYER_TARGET_CHANGED\")\n"
                "f:SetScript(\"OnEvent\", function()\n  MyAddonDB = MyAddonDB or {}\n"
                "  MyAddonDB.lastTargetHealth = UnitHealth(\"target\")\nend)\n"},
        "good": {"TOC": SV_TOC, "core.lua":
                 "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"PLAYER_TARGET_CHANGED\")\n"
                 "f:SetScript(\"OnEvent\", function()\n  MyAddonDB = MyAddonDB or {}\n"
                 "  local hp = UnitHealth(\"target\")\n"
                 "  if not issecretvalue(hp) then\n    MyAddonDB.lastTargetHealth = hp\n  end\nend)\n"},
        "refs": [MIDNIGHT_NOTE, SEC_NOTE + " (rule 3)"],
    },
    {
        "id": "SEC009", "category": "security", "title": "Call to a protected function from addon code",
        "why": "Casting (`CastSpellByName`), using actions (`UseAction`), targeting (`TargetUnit`, `ClearTarget`) "
               "and running macros (`RunMacroText`) are protected: only Blizzard's secure code may call them, "
               "for example when the player clicks a `SecureActionButtonTemplate` button. From addon Lua they are "
               "always blocked (`ADDON_ACTION_FORBIDDEN`), in or out of combat, typically after an AI assistant "
               "\"just calls the API\".",
        "bad": {"TOC": toc(), "core.lua":
                "local btn = CreateFrame(\"Button\", \"MyAddonCastButton\", UIParent, \"UIPanelButtonTemplate\")\n"
                "btn:SetScript(\"OnClick\", function()\n  CastSpellByName(\"Frostbolt\")\nend)\n"},
        "good": {"TOC": toc(), "core.lua":
                 "local btn = CreateFrame(\"Button\", \"MyAddonCastButton\", UIParent, \"SecureActionButtonTemplate\")\n"
                 "btn:RegisterForClicks(\"AnyDown\")\nbtn:SetAttribute(\"type\", \"spell\")\n"
                 "btn:SetAttribute(\"spell\", \"Frostbolt\")\n"},
        "refs": [UI_NOTE, TAINT_NOTE, SEC_NOTE + " (rule 6)"],
    },
    # ------------------------------------------------------------------ SAVEDVARIABLES
    {
        "id": "SV001", "category": "savedvars", "title": "SavedVariables used at file scope (before they load)",
        "why": "WoW executes an addon's Lua files first, then runs its SavedVariables file (which assigns the "
               "saved tables to the globals), then fires `ADDON_LOADED`. At file scope `MyAddonDB` is therefore "
               "always nil: `MyAddonDB = MyAddonDB or {}` builds a throwaway placeholder that the saved table "
               "replaces a moment later. That alone is harmless, but anything that captures it "
               "(`local db = MyAddonDB`), writes defaults into it, or passes it to a migration operates on the "
               "placeholder, so settings seem to reset every login (`warn`). A lone file-scope `X = X or {}` "
               "with no runtime initialisation anywhere is reported as `info`. Note: the First Timers note says "
               "the file-scope pattern works because SVs are parsed first; that is only true with "
               "`## LoadSavedVariablesFirst: 1`, which suppresses this rule.",
        "bad": {"TOC": SV_TOC, "core.lua":
                "MyAddonDB = MyAddonDB or {}\nlocal db = MyAddonDB\n"
                "if db.scale == nil then db.scale = 1 end\nprint(db.scale)\n"},
        "good": {"TOC": SV_TOC, "core.lua":
                 "local addonName, ns = ...\nlocal f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"ADDON_LOADED\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event, loaded)\n  if loaded ~= addonName then return end\n"
                 "  MyAddonDB = MyAddonDB or {}\n  if MyAddonDB.scale == nil then MyAddonDB.scale = 1 end\n"
                 "  ns.db = MyAddonDB\n  self:UnregisterEvent(\"ADDON_LOADED\")\nend)\n"},
        "refs": [SV_NOTE + " (event timeline)", WIKI_SV],
    },
    {
        "id": "SV002", "category": "savedvars", "title": "ADDON_LOADED handler does not check the addon name",
        "why": "`ADDON_LOADED` fires once per addon (including Blizzard load-on-demand modules), with the addon "
               "name as its first argument. Initialising SavedVariables without comparing that name runs the "
               "init for the first addon that loads (before this addon's SVs exist, so defaults overwrite "
               "nothing and get replaced) and again for every later addon, re-merging or resetting data. "
               "Compare against `local addonName = ...` (or the literal folder name) and unregister afterwards.",
        "bad": {"TOC": SV_TOC, "core.lua":
                "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"ADDON_LOADED\")\n"
                "f:SetScript(\"OnEvent\", function(self, event)\n"
                "  MyAddonDB = MyAddonDB or {}\n  MyAddonDB.loads = (MyAddonDB.loads or 0) + 1\nend)\n"},
        "good": {"TOC": SV_TOC, "core.lua":
                 "local addonName = ...\nlocal f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"ADDON_LOADED\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event, loaded)\n  if loaded ~= addonName then return end\n"
                 "  MyAddonDB = MyAddonDB or {}\n  MyAddonDB.loads = (MyAddonDB.loads or 0) + 1\n"
                 "  self:UnregisterEvent(\"ADDON_LOADED\")\nend)\n"},
        "refs": [SV_NOTE + " (`ADDON_LOADED` filtering pattern)", WIKI_SV],
    },
    {
        "id": "SV003", "category": "savedvars", "title": "SavedVariables defaults without a schema version",
        "why": "With more than a handful of nested settings, the next release will rename or restructure a key. "
               "Without a `schemaVersion`/`version` field in the saved table there is no reliable way to know "
               "which layout a player's file has, so migrations guess (and often wipe). Reported once per addon "
               "when the defaults/SV keys reach six and no key containing `version`/`schema` exists. Addons "
               "using AceDB-3.0 are skipped.",
        "bad": {"TOC": SV_TOC, "core.lua":
                "local addonName = ...\nlocal defaults = {\n  enabled = true,\n  scale = 1,\n"
                "  frame = { x = 0, y = 0, point = \"CENTER\" },\n  colors = { r = 1, g = 1, b = 1 },\n}\n"
                "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"ADDON_LOADED\")\n"
                "f:SetScript(\"OnEvent\", function(self, event, loaded)\n  if loaded ~= addonName then return end\n"
                "  MyAddonDB = MyAddonDB or CopyTable(defaults)\nend)\n"},
        "good": {"TOC": SV_TOC, "core.lua":
                 "local addonName = ...\nlocal SCHEMA = 2\nlocal defaults = {\n  schemaVersion = SCHEMA,\n"
                 "  enabled = true,\n  scale = 1,\n  frame = { x = 0, y = 0, point = \"CENTER\" },\n"
                 "  colors = { r = 1, g = 1, b = 1 },\n}\n"
                 "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"ADDON_LOADED\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event, loaded)\n  if loaded ~= addonName then return end\n"
                 "  MyAddonDB = MyAddonDB or CopyTable(defaults)\n"
                 "  if (MyAddonDB.schemaVersion or 1) < SCHEMA then\n    MyAddonDB.colors = MyAddonDB.colors or {}\n"
                 "    MyAddonDB.schemaVersion = SCHEMA\n  end\nend)\n"},
        "refs": [SV_NOTE + " (Migrating SV schema)"],
    },
    {
        "id": "SV004", "category": "savedvars", "title": "Function or frame stored in SavedVariables",
        "why": "SavedVariables serialize only nil, booleans, numbers, strings and tables of those. Functions, "
               "frames, textures and other userdata are dropped (or break the write), so whatever depended on "
               "them is gone next session. Store a frame's name or position, or a key that selects a function, "
               "and keep live objects in a non-saved table. Writes through aliases such as "
               "`ns.db = MyAddonDB` and `local db = MyAddonDB` are followed.",
        "bad": {"TOC": SV_TOC, "core.lua":
                "local addonName = ...\nlocal f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"ADDON_LOADED\")\n"
                "f:SetScript(\"OnEvent\", function(self, event, loaded)\n  if loaded ~= addonName then return end\n"
                "  MyAddonDB = MyAddonDB or {}\n  MyAddonDB.anchor = CreateFrame(\"Frame\", nil, UIParent)\n"
                "  MyAddonDB.onClick = function() print(\"clicked\") end\nend)\n"},
        "good": {"TOC": SV_TOC, "core.lua":
                 "local addonName = ...\nlocal anchor = CreateFrame(\"Frame\", \"MyAddonAnchor\", UIParent)\n"
                 "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"ADDON_LOADED\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event, loaded)\n  if loaded ~= addonName then return end\n"
                 "  MyAddonDB = MyAddonDB or {}\n  MyAddonDB.anchorName = anchor:GetName()\n"
                 "  MyAddonDB.clickAction = \"print\"\nend)\n"},
        "refs": [SV_NOTE + " (What can be saved)", WIKI_SV],
    },
    {
        "id": "SV005", "category": "savedvars", "title": "Per-character SavedVariables keyed by character",
        "why": "`## SavedVariablesPerCharacter` already writes one file per character. Indexing that table by "
               "`UnitName(\"player\")` or `GetRealmName()` adds nothing (each file only ever holds its own "
               "character) and usually means the data was meant to be account-wide, e.g. an alt overview that "
               "will never see the other characters. Either drop the key or move the table to "
               "`## SavedVariables`. Account-wide tables keyed per character are fine. Low confidence.",
        "bad": {"TOC": toc(per_char="MyAddonCharDB"), "core.lua":
                "local addonName = ...\nlocal f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"PLAYER_LOGIN\")\n"
                "f:SetScript(\"OnEvent\", function()\n  MyAddonCharDB = MyAddonCharDB or {}\n"
                "  local key = UnitName(\"player\") .. \"-\" .. GetRealmName()\n"
                "  MyAddonCharDB[key] = { gold = GetMoney() }\nend)\n"},
        "good": {"TOC": toc(sv="MyAddonDB", per_char="MyAddonCharDB"), "core.lua":
                 "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"PLAYER_LOGIN\")\n"
                 "f:SetScript(\"OnEvent\", function()\n  MyAddonCharDB = MyAddonCharDB or {}\n"
                 "  MyAddonCharDB.gold = GetMoney()\n  MyAddonDB = MyAddonDB or {}\n"
                 "  local key = UnitName(\"player\") .. \"-\" .. GetRealmName()\n"
                 "  MyAddonDB[key] = { gold = GetMoney() }\nend)\n"},
        "refs": [SV_NOTE + " (Per-character vs per-account decisions)"],
    },
    {
        "id": "SV006", "category": "savedvars", "title": "SavedVariables table replaced after load",
        "why": "`MyAddonDB = {}` (or a fresh copy of the defaults) inside a runtime function throws away "
               "everything the player saved. It is usually a misplaced initialisation that should have been "
               "`MyAddonDB = MyAddonDB or {}` plus per-key defaults. Replacements guarded by a check on the SV "
               "itself, inside load/init event handlers, or in an explicit reset path (a `reset` slash "
               "argument, a function named `Reset...`, a StaticPopup `OnAccept`) are not reported.",
        "bad": {"TOC": SV_TOC, "core.lua":
                "local function RecordLoot(itemLink)\n  MyAddonDB = { loot = {} }\n"
                "  table.insert(MyAddonDB.loot, itemLink)\nend\n"
                "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"CHAT_MSG_LOOT\")\n"
                "f:SetScript(\"OnEvent\", function(self, event, text)\n  RecordLoot(text)\nend)\n"},
        "good": {"TOC": SV_TOC, "core.lua":
                 "local function RecordLoot(itemLink)\n  MyAddonDB = MyAddonDB or {}\n"
                 "  MyAddonDB.loot = MyAddonDB.loot or {}\n  table.insert(MyAddonDB.loot, itemLink)\nend\n"
                 "SLASH_MYADDON1 = \"/myaddon\"\nSlashCmdList.MYADDON = function(msg)\n"
                 "  if msg == \"reset\" then MyAddonDB = {} end\nend\n"
                 "local f = CreateFrame(\"Frame\")\nf:RegisterEvent(\"CHAT_MSG_LOOT\")\n"
                 "f:SetScript(\"OnEvent\", function(self, event, text)\n  RecordLoot(text)\nend)\n"},
        "refs": [SV_NOTE, WIKI_SV],
    },
]
