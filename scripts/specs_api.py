"""Fixture/doc specs for API rules (``python scripts/new_fixture.py scripts/specs_api.py --force``)."""

FOREVER_TOC = "## Interface: 16001\n## Title: Fixture\n## Notes: auditor fixture\n## Version: 1.0\n\ncore.lua\n"
FOREVER_NOTES = "First Timers `06-notes/forever-quirks.md` and `06-notes/forever-rules.md`"
LOOKUP = "`addon-auditor api <Symbol>` to check a symbol per client"

SPECS = [
    {
        "id": "API001", "category": "api", "title": "Call to a C_ namespace member that does not exist",
        "why": "The namespace is real but the member is not part of it on any client the addon targets. This is "
               "the typical shape of an API invented by an AI assistant (`C_ChatInfo.SendMessage`, "
               "`C_PlayerInteractionManager.IsInteractingWith`) or a misspelling. The call throws "
               "`attempt to call a nil value`. Existence-checked calls (`if C_X and C_X.F then`, `C_X.F and "
               "C_X.F()`, `pcall`) are not reported. When the addon also targets a client without bundled API "
               "data (Classic), the finding is downgraded to info.",
        "bad": {"core.lua": "local function Announce(text)\n"
                            "  C_ChatInfo.SendMessage({ message = text, chatType = \"SAY\" })\n"
                            "end\nAnnounce(\"hello\")\n"},
        "good": {"core.lua": "local function Announce(text)\n"
                             "  if C_ChatInfo and C_ChatInfo.SendMessage then\n"
                             "    C_ChatInfo.SendMessage({ message = text, chatType = \"SAY\" })\n"
                             "  else\n"
                             "    C_ChatInfo.SendChatMessage(text, \"SAY\")\n"
                             "  end\n"
                             "end\n"
                             "local CI = C_ChatInfo\n"
                             "local ok = CI.SendMessage and pcall(CI.SendMessage, {})\n"
                             "Announce(tostring(ok))\n"},
        "refs": [LOOKUP],
    },
    {
        "id": "API002", "category": "api", "title": "Unknown C_ namespace",
        "why": "No targeted client has this `C_*` namespace and the addon does not create it, so the first index "
               "throws `attempt to index a nil value` and the rest of the file stops loading. Guarded reads "
               "(`if C_X then`, `C_X and C_X.F`) are not reported.",
        "bad": {"core.lua": "local function Shout(text)\n  C_PartyChat.Send(text)\nend\nShout(\"hi\")\n"},
        "good": {"core.lua": "local function Shout(text)\n"
                             "  if C_PartyChat and C_PartyChat.Send then\n"
                             "    C_PartyChat.Send(text)\n"
                             "  else\n"
                             "    C_ChatInfo.SendChatMessage(text, \"PARTY\")\n"
                             "  end\n"
                             "end\nShout(\"hi\")\n"},
        "refs": [LOOKUP],
    },
    {
        "id": "API003", "category": "api", "title": "API missing on some targeted clients",
        "why": "The addon targets several clients (for example `## Interface: 16001, 120107` for Forever and "
               "Mainline) but calls an API that only one of them has. It works where it was tested and throws "
               "`attempt to call/index a nil value` on the other. Calls guarded by an existence check or by a "
               "client check (`WOW_PROJECT_ID`, `isRetail`, ...) are not reported, and files loaded only for one "
               "client (per-client TOC or `[AllowLoadGameType ...]`) are judged against that client only. Plain "
               "globals are only reported as missing on Mainline, because the Forever data omits undocumented "
               "C functions.",
        "bad": {"core.lua": "local function Stage()\n  return C_Scenario.GetInfo()\nend\nprint(Stage())\n"},
        "good": {"core.lua": "local function Stage()\n"
                             "  if C_Scenario and C_Scenario.GetInfo then\n"
                             "    return C_Scenario.GetInfo()\n"
                             "  end\n"
                             "end\n"
                             "local function Stage2()\n"
                             "  if WOW_PROJECT_ID ~= WOW_PROJECT_MAINLINE then return end\n"
                             "  return C_Scenario.GetInfo()\n"
                             "end\nprint(Stage(), Stage2())\n"},
        "refs": [LOOKUP],
    },
    {
        "id": "API004", "category": "api", "title": "Deprecated API",
        "why": "Deprecated functions survive only as compatibility shims (`Blizzard_Deprecated*`) and are removed "
               "in a later patch. On Forever and Midnight the chat shims (`SendChatMessage`, `ChatFrame_OpenChat`, "
               "`ChatFrame_AddMessageEventFilter`, ...) are only defined while the `loadDeprecationFallbacks` CVar "
               "is on, so they can already be nil for some players. Move to the replacement now; keep the old name only as a guarded fallback "
               "(`local GetItemCount = C_Item and C_Item.GetItemCount or GetItemCount` is not reported).",
        "bad": {"core.lua": "local count = GetItemCount(6948)\nprint(count)\n"},
        "good": {"core.lua": "local count = C_Item.GetItemCount(6948)\n"
                             "local Legacy = C_Item and C_Item.GetItemCount or GetItemCount\n"
                             "print(count, Legacy(6948))\n"},
        "refs": [LOOKUP, "Warcraft Wiki: API change summaries"],
    },
    {
        "id": "API005", "category": "api", "title": "Protected call that addons cannot make on Forever",
        "why": "`TargetUnit`, `TargetByName`, `TargetLastTarget`, `ClearTarget` and the `TargetNearest*` family "
               "are protected. On Forever calling them from addon code shows an 'Interface action failed' popup "
               "and `pcall` does not hide it. `ChatFrame_OpenChat` / `ChatEdit_ActivateChat` fail silently "
               "(reported as a warning). Let the player act through a secure button or macro instead.",
        "bad": {"TOC": FOREVER_TOC,
                "core.lua": "local function Focus(name)\n  TargetUnit(name)\nend\nFocus(\"Hogger\")\n"},
        "good": {"TOC": FOREVER_TOC,
                 "core.lua": "local btn = CreateFrame(\"Button\", \"FixtureTargetButton\", UIParent,\n"
                             "  \"SecureActionButtonTemplate\")\n"
                             "btn:SetAttribute(\"type\", \"macro\")\n"
                             "btn:SetAttribute(\"macrotext\", \"/target Hogger\")\n"},
        "refs": [FOREVER_NOTES, "Warcraft Wiki: TargetUnit (#protected)"],
    },
    {
        "id": "API006", "category": "api", "title": "Combat log (CLEU) used where addons cannot read it",
        "why": "Forever does not deliver `COMBAT_LOG_EVENT_UNFILTERED` to addons, and on Midnight (12.0+) "
               "registering it errors; `CombatLogGetCurrentEventInfo` is unavailable to addon code on both. A "
               "CLEU-driven feature silently does nothing. Build on unit events, encounter events or the "
               "built-in damage meter. Code inside a client check (`if not isForever then`) is not reported.",
        "bad": {"TOC": FOREVER_TOC,
                "core.lua": "local f = CreateFrame(\"Frame\")\n"
                            "f:RegisterEvent(\"COMBAT_LOG_EVENT_UNFILTERED\")\n"
                            "f:SetScript(\"OnEvent\", function()\n"
                            "  local _, sub = CombatLogGetCurrentEventInfo()\n"
                            "  print(sub)\n"
                            "end)\n"},
        "good": {"TOC": FOREVER_TOC,
                 "core.lua": "local f = CreateFrame(\"Frame\")\n"
                             "f:SetScript(\"OnEvent\", function(_, _, unit, _, spellID)\n"
                             "  print(unit, spellID)\n"
                             "end)\n"
                             "f:RegisterUnitEvent(\"UNIT_SPELLCAST_SUCCEEDED\", \"player\")\n"},
        "refs": [FOREVER_NOTES, "First Timers `06-notes/addon-dev/midnight-12.md` (CLEU is gone for addons)"],
    },
    {
        "id": "API007", "category": "api", "title": "UnitName's second return treated as a realm on Forever",
        "why": "On Forever `UnitName` and `UnitNameUnmodified` return `(firstName, surname)`. Code written for "
               "Mainline that stores the second value as `realm` or joins `name .. \"-\" .. realm` produces wrong "
               "whisper targets, mail recipients and dedupe keys. Use `UnitGUID` for identity, "
               "`GetNormalizedRealmName()` for the realm, and `first .. \" \" .. surname` for display.",
        "bad": {"TOC": FOREVER_TOC,
                "core.lua": "local function FullName(unit)\n"
                            "  local name, realm = UnitName(unit)\n"
                            "  return name .. \"-\" .. (realm or GetNormalizedRealmName())\n"
                            "end\nprint(FullName(\"target\"))\n"},
        "good": {"TOC": FOREVER_TOC,
                 "core.lua": "local function DisplayName(unit)\n"
                             "  local first, surname = UnitName(unit)\n"
                             "  if surname and surname ~= \"\" then\n"
                             "    return first .. \" \" .. surname\n"
                             "  end\n"
                             "  return first\n"
                             "end\nprint(DisplayName(\"target\"), UnitGUID(\"target\"))\n"},
        "refs": [FOREVER_NOTES],
    },
    {
        "id": "API008", "category": "api", "title": "Chat language taken from GetDefaultLanguage",
        "why": "`GetDefaultLanguage()` returns the language *name* (`\"Common\"`) and then its numeric ID. The send "
               "API's third argument is a languageID; on Forever passing the name throws `outside of expected "
               "range 0 to 4294967295`. As the last argument it also spills the ID into the `target` slot. Pass "
               "`nil` to speak the character's default language.",
        "bad": {"core.lua": "local function Say(text)\n"
                            "  local lang = GetDefaultLanguage(\"player\")\n"
                            "  C_ChatInfo.SendChatMessage(text, \"SAY\", lang)\n"
                            "end\nSay(\"hello\")\n"},
        "good": {"core.lua": "local function Say(text)\n"
                             "  C_ChatInfo.SendChatMessage(text, \"SAY\", nil)\n"
                             "end\nSay(\"hello\")\n"},
        "refs": [FOREVER_NOTES],
    },
    {
        "id": "API009", "category": "api", "title": "GetItemInfo result used without a nil check",
        "why": "Item data is streamed from the server. `GetItemInfo` / `C_Item.GetItemInfo` return nil for an item "
               "the client has not cached yet, so `name:upper()`, `\"[\" .. name .. \"]\"` or `ilvl > 100` throw "
               "the first time a new item is seen (and work on the next /reload, which hides the bug). Check for "
               "nil and retry when `GET_ITEM_INFO_RECEIVED` fires, or use `Item:ContinueOnItemLoad`.",
        "bad": {"core.lua": "local function Label(itemID)\n"
                            "  local name, _, quality = C_Item.GetItemInfo(itemID)\n"
                            "  return \"[\" .. name .. \"] q\" .. quality\n"
                            "end\nprint(Label(6948))\n"},
        "good": {"core.lua": "local function Label(itemID)\n"
                             "  local name, _, quality = C_Item.GetItemInfo(itemID)\n"
                             "  if not name then\n"
                             "    C_Item.RequestLoadItemDataByID(itemID)\n"
                             "    return nil\n"
                             "  end\n"
                             "  return \"[\" .. name .. \"] q\" .. quality\n"
                             "end\nprint(Label(6948))\n"},
        "refs": ["Warcraft Wiki: GET_ITEM_INFO_RECEIVED, ItemMixin:ContinueOnItemLoad"],
    },
]
