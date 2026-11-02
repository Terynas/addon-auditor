"""Fixture/doc specs for UX rules.  Usage: python scripts/new_fixture.py scripts/specs_ux.py [--force]"""

UI_SKILL = "Workspace skill `wow-addon-ui` (`.cursor/skills/wow-addon-ui/SKILL.md`)"
NOTES_UI = "First Timers `06-notes/addon-dev/ui-and-secure-templates.md`"
NOTES_SLASH = "First Timers `06-notes/addon-dev/slash-commands.md`"
NOTES_LOC = "First Timers `06-notes/addon-dev/localization.md`"
NOTES_SV = "First Timers `06-notes/addon-dev/savedvariables-and-load-order.md`"
NOTES_API = "First Timers `06-notes/addon-dev/api-events-frames.md` (Print and chat output)"
QUIRKS = "First Timers `06-notes/forever-quirks.md` (UI templates that break Forever frames)"

TOC = "## Interface: 16001, 120107\n## Title: Fixture\n## Notes: auditor fixture\n## Version: 1.0\n"
TOC_SV = TOC + "## SavedVariables: FixtureDB\n\ncore.lua\n"

WINDOW = """local f = CreateFrame("Frame", "FixtureWindow", UIParent, "BasicFrameTemplateWithInset")
f:SetSize(320, 240)
f:SetPoint("CENTER")
f:Hide()
"""

SPECS = [
    {
        "id": "UX001", "category": "ux", "title": "Windowed addon without a slash command",
        "why": "Players open addon windows from chat (`/myaddon`) or bind them in macros. A window with no slash "
               "command can only be reached through whatever button the addon happens to provide, and is lost "
               "entirely if that button is hidden.",
        "bad": {"core.lua": WINDOW},
        "good": {"core.lua": WINDOW + "tinsert(UISpecialFrames, \"FixtureWindow\")\n\nSLASH_FIXTURE1 = \"/fixture\"\n"
                 "SlashCmdList.FIXTURE = function(msg)\n    f:SetShown(not f:IsShown())\nend\n"},
        "refs": [NOTES_SLASH, UI_SKILL + " — checklist: test in game with the addon's own slash command"],
    },
    {
        "id": "UX002", "category": "ux", "title": "Slash command ignores its arguments or has no help",
        "why": "A slash handler that silently ignores unknown input leaves the player guessing. Always handle an empty "
               "`msg` and `help`, and answer anything unrecognised with the list of sub-commands. When the addon has "
               "a window, options and a minimap button, a handler that ignores `msg` hides most of them from chat.",
        "bad": {"core.lua": "FixtureDB = FixtureDB or {}\n\nSLASH_FIXTURE1 = \"/fixture\"\n"
                "SlashCmdList.FIXTURE = function(msg)\n    if msg == \"reset\" then\n        FixtureDB = {}\n"
                "    end\nend\n"},
        "good": {"core.lua": "FixtureDB = FixtureDB or {}\n\nSLASH_FIXTURE1 = \"/fixture\"\n"
                 "SlashCmdList.FIXTURE = function(msg)\n    local cmd = (msg or \"\"):lower():match(\"^%s*(%S*)\")\n"
                 "    if cmd == \"reset\" then\n        FixtureDB = {}\n        print(\"Fixture: reset.\")\n    else\n"
                 "        print(\"/fixture reset - clear saved data\")\n        print(\"/fixture help - this list\")\n"
                 "    end\nend\n"},
        "refs": [NOTES_SLASH + " (Help output convention, best practices)"],
    },
    {
        "id": "UX003", "category": "ux", "title": "Window does not close with Escape",
        "why": "Every Blizzard window closes with Esc, so players expect addon windows to do the same. A window that "
               "ignores Esc forces a hunt for its close button (and Esc opens the game menu instead). Add the "
               "window's global name to `UISpecialFrames`; unnamed frames cannot be registered, so give windows a "
               "name.",
        "bad": {"core.lua": WINDOW},
        "good": {"core.lua": WINDOW + "tinsert(UISpecialFrames, \"FixtureWindow\")\n\nSLASH_FIXTURE1 = \"/fixture\"\n"
                 "SlashCmdList.FIXTURE = function()\n    f:SetShown(not f:IsShown())\nend\n"},
        "refs": [UI_SKILL + " — Window behaviour: add the global frame name to `UISpecialFrames`"],
    },
    {
        "id": "UX004", "category": "ux", "title": "Movable frame not clamped to screen",
        "why": "A movable frame can be dragged partly or fully off-screen, or end up there after a resolution or UI "
               "scale change. Without `SetClampedToScreen(true)` the player may never get it back without deleting "
               "SavedVariables or layout cache.",
        "bad": {"core.lua": "local f = CreateFrame(\"Frame\", \"FixtureMover\", UIParent, \"BackdropTemplate\")\n"
                "f:SetSize(200, 100)\nf:SetPoint(\"CENTER\")\nf:SetMovable(true)\nf:EnableMouse(true)\n"
                "f:RegisterForDrag(\"LeftButton\")\nf:SetScript(\"OnDragStart\", f.StartMoving)\n"
                "f:SetScript(\"OnDragStop\", f.StopMovingOrSizing)\n"},
        "good": {"core.lua": "local f = CreateFrame(\"Frame\", \"FixtureMover\", UIParent, \"BackdropTemplate\")\n"
                 "f:SetSize(200, 100)\nf:SetPoint(\"CENTER\")\nf:SetMovable(true)\nf:SetClampedToScreen(true)\n"
                 "f:EnableMouse(true)\nf:RegisterForDrag(\"LeftButton\")\n"
                 "f:SetScript(\"OnDragStart\", f.StartMoving)\nf:SetScript(\"OnDragStop\", f.StopMovingOrSizing)\n"},
        "refs": [UI_SKILL + " — Window behaviour: `SetClampedToScreen(true)`"],
    },
    {
        "id": "UX005", "category": "ux", "title": "Movable frame position is not saved",
        "why": "If a player moves a frame and it snaps back to the default spot on every reload, moving it was "
               "pointless. Store the anchor from `GetPoint()` in SavedVariables when dragging stops and restore it "
               "on load. Named frames moved with `StartMoving` are kept by the client layout cache, so the rule "
               "only reports anonymous frames (or ones with `SetDontSavePosition(true)`).",
        "bad": {"TOC": TOC_SV, "core.lua": "local f = CreateFrame(\"Frame\", nil, UIParent)\n"
                "f:SetSize(200, 100)\nf:SetPoint(\"CENTER\")\nf:SetMovable(true)\nf:SetClampedToScreen(true)\n"
                "f:EnableMouse(true)\nf:RegisterForDrag(\"LeftButton\")\n"
                "f:SetScript(\"OnDragStart\", f.StartMoving)\nf:SetScript(\"OnDragStop\", f.StopMovingOrSizing)\n"},
        "good": {"TOC": TOC_SV, "core.lua": "FixtureDB = FixtureDB or {}\n\n"
                 "local f = CreateFrame(\"Frame\", nil, UIParent)\n"
                 "f:SetSize(200, 100)\nf:SetPoint(\"CENTER\")\nf:SetMovable(true)\nf:SetClampedToScreen(true)\n"
                 "f:EnableMouse(true)\nf:RegisterForDrag(\"LeftButton\")\n"
                 "f:SetScript(\"OnDragStart\", f.StartMoving)\nf:SetScript(\"OnDragStop\", function(self)\n"
                 "    self:StopMovingOrSizing()\n    local point, _, relativePoint, x, y = self:GetPoint()\n"
                 "    FixtureDB.position = { point = point, relativePoint = relativePoint, x = x, y = y }\nend)\n"},
        "refs": [NOTES_UI + " (Custom positioning the user can drag)", NOTES_SV],
    },
    {
        "id": "UX006", "category": "ux", "title": "Drag registered without a working StartMoving/StopMovingOrSizing pair",
        "why": "`RegisterForDrag` only enables drag events; without an `OnDragStart` that calls `StartMoving` the "
               "frame does not move. Calling `StartMoving` without a matching `StopMovingOrSizing` in `OnDragStop` "
               "leaves the frame stuck to the cursor after the mouse button is released.",
        "bad": {"core.lua": "local f = CreateFrame(\"Frame\", \"FixtureDrag\", UIParent)\nf:SetSize(200, 100)\n"
                "f:SetPoint(\"CENTER\")\nf:SetMovable(true)\nf:SetClampedToScreen(true)\nf:EnableMouse(true)\n"
                "f:RegisterForDrag(\"LeftButton\")\nf:SetScript(\"OnDragStart\", f.StartMoving)\n"},
        "good": {"core.lua": "local f = CreateFrame(\"Frame\", \"FixtureDrag\", UIParent)\nf:SetSize(200, 100)\n"
                 "f:SetPoint(\"CENTER\")\nf:SetMovable(true)\nf:SetClampedToScreen(true)\nf:EnableMouse(true)\n"
                 "f:RegisterForDrag(\"LeftButton\")\nf:SetScript(\"OnDragStart\", f.StartMoving)\n"
                 "f:SetScript(\"OnDragStop\", f.StopMovingOrSizing)\n"},
        "refs": [NOTES_UI + " (Custom positioning the user can drag)"],
    },
    {
        "id": "UX007", "category": "ux", "title": "Minimap button cannot be hidden",
        "why": "The minimap ring fills up quickly. Players expect every minimap button to have a \"Show minimap "
               "icon\" option (or `/cmd minimap`); without one the only way to remove it is to disable the addon. "
               "LibDBIcon honours a `hide` key in the table you register, so store one in SavedVariables.",
        "bad": {"TOC": TOC_SV, "core.lua": "FixtureDB = FixtureDB or {}\n\n"
                "local btn = CreateFrame(\"Button\", \"FixtureMinimapButton\", Minimap)\nbtn:SetSize(32, 32)\n"
                "btn:SetPoint(\"CENTER\", Minimap, \"CENTER\", -70, 0)\n"
                "btn:SetNormalTexture(\"Interface\\\\Icons\\\\INV_Misc_QuestionMark\")\n"},
        "good": {"TOC": TOC_SV, "core.lua": "FixtureDB = FixtureDB or { minimap = { hide = false } }\n\n"
                 "local btn = CreateFrame(\"Button\", \"FixtureMinimapButton\", Minimap)\nbtn:SetSize(32, 32)\n"
                 "btn:SetPoint(\"CENTER\", Minimap, \"CENTER\", -70, 0)\n"
                 "btn:SetNormalTexture(\"Interface\\\\Icons\\\\INV_Misc_QuestionMark\")\n"
                 "btn:SetShown(not FixtureDB.minimap.hide)\n"},
        "refs": [UI_SKILL + " — Minimap button: a \"Show minimap icon\" option toggles `db.hide`"],
    },
    {
        "id": "UX008", "category": "ux", "title": "Settings stored but no options panel",
        "why": "Players look for addon settings under Options -> AddOns. If the addon keeps settings in "
               "SavedVariables but registers no panel there, they can only be changed through slash commands the "
               "player has to discover. This is a low-confidence hint: small addons can be fine with slash-only "
               "settings.",
        "bad": {"TOC": TOC_SV, "core.lua": "local defaults = { scale = 1, locked = false }\n\n"
                "FixtureDB = FixtureDB or CopyTable(defaults)\n"},
        "good": {"TOC": TOC_SV, "core.lua": "local defaults = { scale = 1, locked = false }\n\n"
                 "FixtureDB = FixtureDB or CopyTable(defaults)\n\n"
                 "if Settings and Settings.RegisterVerticalLayoutCategory then\n"
                 "    local category = Settings.RegisterVerticalLayoutCategory(\"Fixture\")\n"
                 "    Settings.RegisterAddOnCategory(category)\nend\n"},
        "refs": [UI_SKILL + " — Options page", NOTES_UI + " (Settings API)"],
    },
    {
        "id": "UX009", "category": "ux", "title": "Options registered only with the removed InterfaceOptions API",
        "why": "`InterfaceOptions_AddCategory` was deprecated in 10.0 and removed from Mainline; an addon that only "
               "uses it has no options page there (or errors if it calls it unguarded). Register through "
               "`Settings` and keep the old call as a fallback for clients without it:\n\n"
               "```lua\nif Settings and Settings.RegisterCanvasLayoutCategory then\n"
               "    local category = Settings.RegisterCanvasLayoutCategory(panel, panel.name)\n"
               "    Settings.RegisterAddOnCategory(category)\nelse\n    InterfaceOptions_AddCategory(panel)\nend\n```",
        "bad": {"core.lua": "local panel = CreateFrame(\"Frame\")\npanel.name = \"Fixture\"\n"
                "InterfaceOptions_AddCategory(panel)\n"},
        "good": {"core.lua": "local panel = CreateFrame(\"Frame\")\npanel.name = \"Fixture\"\n"
                 "if Settings and Settings.RegisterCanvasLayoutCategory then\n"
                 "    local category = Settings.RegisterCanvasLayoutCategory(panel, panel.name)\n"
                 "    Settings.RegisterAddOnCategory(category)\nelseif InterfaceOptions_AddCategory then\n"
                 "    InterfaceOptions_AddCategory(panel)\nend\n"},
        "refs": [NOTES_UI + " (Settings API)", UI_SKILL + " — Options page", QUIRKS.replace(
            "(UI templates that break Forever frames)", "(Settings: keep `InterfaceOptions_AddCategory` fallback)")],
    },
    {
        "id": "UX010", "category": "ux", "title": "Unconditional chat output on login",
        "why": "Every \"MyAddon v1.2 loaded!\" line pushes the player's chat up; with a dozen addons the login chat is "
               "a wall of banners. Print on first run or after an update, or behind an opt-in option. Warnings about "
               "real problems and debug output are not reported. One line is `info`; several are `warn`.",
        "bad": {"core.lua": "print(\"Fixture loaded. Type /fixture for options.\")\n\n"
                "local frame = CreateFrame(\"Frame\")\nframe:RegisterEvent(\"PLAYER_LOGIN\")\n"
                "frame:SetScript(\"OnEvent\", function(self, event)\n    if event == \"PLAYER_LOGIN\" then\n"
                "        print(\"Fixture ready.\")\n    end\nend)\n"},
        "good": {"TOC": TOC_SV, "core.lua": "local frame = CreateFrame(\"Frame\")\nframe:RegisterEvent(\"PLAYER_LOGIN\")\n"
                 "frame:SetScript(\"OnEvent\", function(self, event)\n    if event == \"PLAYER_LOGIN\" then\n"
                 "        FixtureDB = FixtureDB or {}\n        if not FixtureDB.welcomeSeen then\n"
                 "            print(\"Fixture: type /fixture for options.\")\n            FixtureDB.welcomeSeen = true\n"
                 "        end\n    end\nend)\n"},
        "refs": [NOTES_API, UI_SKILL + " — First-open intro: show a short guide once (store `introSeen`)"],
    },
    {
        "id": "UX011", "category": "ux", "title": "Popup or window opened on every login",
        "why": "A StaticPopup or addon window that opens on every login blocks the player before they can move and "
               "trains them to dismiss it unread. Show intros once (store a seen-flag) and what's-new notes only "
               "when the stored version changes.",
        "bad": {"core.lua": "StaticPopupDialogs.FIXTURE_WELCOME = { text = \"Welcome to Fixture!\", button1 = OKAY }\n\n"
                "local frame = CreateFrame(\"Frame\")\nframe:RegisterEvent(\"PLAYER_LOGIN\")\n"
                "frame:SetScript(\"OnEvent\", function(self, event)\n    if event == \"PLAYER_LOGIN\" then\n"
                "        StaticPopup_Show(\"FIXTURE_WELCOME\")\n    end\nend)\n"},
        "good": {"TOC": TOC_SV, "core.lua": "StaticPopupDialogs.FIXTURE_WELCOME = { text = \"Welcome to Fixture!\", "
                 "button1 = OKAY }\n\nlocal frame = CreateFrame(\"Frame\")\nframe:RegisterEvent(\"PLAYER_LOGIN\")\n"
                 "frame:SetScript(\"OnEvent\", function(self, event)\n    if event == \"PLAYER_LOGIN\" then\n"
                 "        FixtureDB = FixtureDB or {}\n        if not FixtureDB.introSeen then\n"
                 "            StaticPopup_Show(\"FIXTURE_WELCOME\")\n            FixtureDB.introSeen = true\n"
                 "        end\n    end\nend)\n"},
        "refs": [UI_SKILL + " — First-open intro: \"never a modal popup on login\""],
    },
    {
        "id": "UX012", "category": "ux", "title": "SetBackdrop on a frame without BackdropTemplate",
        "why": "Since patch 9.0 `SetBackdrop` and friends come from `BackdropTemplateMixin`; Forever, Classic Era and "
               "Mainline all require the `BackdropTemplate` template. Without it the call throws `attempt to call "
               "method 'SetBackdrop' (a nil value)` and the rest of the file stops loading. The rule follows the "
               "frame from `CreateFrame` (including helpers it is passed to) and stays quiet when the template is a "
               "variable or the call is guarded with `if f.SetBackdrop then`.",
        "bad": {"core.lua": "local f = CreateFrame(\"Frame\", nil, UIParent)\nf:SetSize(200, 100)\n"
                "f:SetPoint(\"CENTER\")\nf:SetBackdrop({ bgFile = \"Interface\\\\Buttons\\\\WHITE8X8\" })\n"},
        "good": {"core.lua": "local f = CreateFrame(\"Frame\", nil, UIParent, \"BackdropTemplate\")\nf:SetSize(200, 100)\n"
                 "f:SetPoint(\"CENTER\")\nf:SetBackdrop({ bgFile = \"Interface\\\\Buttons\\\\WHITE8X8\" })\n"},
        "refs": [UI_SKILL + " — Chrome: all frames with a backdrop need `BackdropTemplate`",
                 QUIRKS.replace("(UI templates that break Forever frames)", "(use `BackdropTemplate` for custom frames)")],
    },
    {
        "id": "UX013", "category": "ux", "title": "User-facing text bypasses the locale table",
        "why": "Once an addon ships a locale table, every hard-coded English label or chat line shows up untranslated "
               "for German, French or Russian players next to translated text. Only literal sentences passed to "
               "`SetText`, `AddLine`, `SetFormattedText` or `print` are counted, and each file gets one aggregated "
               "finding.",
        "bad": {"TOC": TOC + "\nLocales/enUS.lua\ncore.lua\n",
                "core.lua": "local L = FixtureLocale\n\nlocal f = CreateFrame(\"Frame\", nil, UIParent)\n"
                "local title = f:CreateFontString(nil, \"OVERLAY\", \"GameFontNormal\")\ntitle:SetText(L[\"Fixture\"])\n"
                "local hint = f:CreateFontString(nil, \"OVERLAY\", \"GameFontHighlightSmall\")\n"
                "hint:SetText(\"Drag items here to add them to the list.\")\n",
                "Locales/enUS.lua": "local L = {}\nL[\"Fixture\"] = \"Fixture\"\nL[\"Options\"] = \"Options\"\n"
                "L[\"Drag items here to add them to the list.\"] = \"Drag items here to add them to the list.\"\n"
                "FixtureLocale = L\n"},
        "good": {"TOC": TOC + "\nLocales/enUS.lua\ncore.lua\n",
                 "core.lua": "local L = FixtureLocale\n\nlocal f = CreateFrame(\"Frame\", nil, UIParent)\n"
                 "local title = f:CreateFontString(nil, \"OVERLAY\", \"GameFontNormal\")\ntitle:SetText(L[\"Fixture\"])\n"
                 "local hint = f:CreateFontString(nil, \"OVERLAY\", \"GameFontHighlightSmall\")\n"
                 "hint:SetText(L[\"Drag items here to add them to the list.\"])\n",
                 "Locales/enUS.lua": "local L = {}\nL[\"Fixture\"] = \"Fixture\"\nL[\"Options\"] = \"Options\"\n"
                 "L[\"Drag items here to add them to the list.\"] = \"Drag items here to add them to the list.\"\n"
                 "FixtureLocale = L\n"},
        "refs": [NOTES_LOC],
    },
    {
        "id": "UX014", "category": "ux", "title": "Hard-coded client font path",
        "why": "Client font files differ per locale: `FRIZQT__.TTF` has no Cyrillic or CJK glyphs, so Russian, Korean "
               "and Chinese players see empty boxes. Hard-coded paths also ignore UI font replacements. Blizzard "
               "font objects (`GameFontNormal`, `GameFontHighlightSmall`, ...) resolve to the right file for each "
               "locale. Custom fonts shipped inside the addon are not reported.",
        "bad": {"core.lua": "local f = CreateFrame(\"Frame\", nil, UIParent)\n"
                "local label = f:CreateFontString(nil, \"OVERLAY\")\n"
                "label:SetFont(\"Fonts\\\\FRIZQT__.TTF\", 14, \"OUTLINE\")\n"},
        "good": {"core.lua": "local f = CreateFrame(\"Frame\", nil, UIParent)\n"
                 "local label = f:CreateFontString(nil, \"OVERLAY\")\nlabel:SetFontObject(GameFontNormal)\n"},
        "refs": [NOTES_UI + " (Font strings: built-in font objects)", UI_SKILL + " — Typography", NOTES_LOC],
    },
    {
        "id": "UX015", "category": "ux", "title": "UICheckButtonTemplate on Forever",
        "why": "Machine-observed on Forever (Interface 16001): building check buttons from `UICheckButtonTemplate` "
               "took down the ForeverDungeons UI. Use `Settings.CreateCheckbox` on a "
               "`Settings.RegisterVerticalLayoutCategory` page, or build the check button yourself "
               "(`CreateFrame(\"CheckButton\")` + `UI-CheckBox-Up` / `UI-CheckBox-Check` textures + a FontString "
               "label). Usage that only runs when `Settings` is missing (the standard UI kit's legacy fallback) is "
               "not reported. Runs only for addons whose TOC targets Forever.",
        "bad": {"core.lua": "local panel = CreateFrame(\"Frame\")\n"
                "local check = CreateFrame(\"CheckButton\", nil, panel, \"UICheckButtonTemplate\")\n"
                "check:SetPoint(\"TOPLEFT\", 16, -16)\n"},
        "good": {"core.lua": "local panel = CreateFrame(\"Frame\")\n"
                 "local check = CreateFrame(\"CheckButton\", nil, panel)\ncheck:SetSize(24, 24)\n"
                 "check:SetPoint(\"TOPLEFT\", 16, -16)\n"
                 "check:SetNormalTexture(\"Interface\\\\Buttons\\\\UI-CheckBox-Up\")\n"
                 "check:SetPushedTexture(\"Interface\\\\Buttons\\\\UI-CheckBox-Down\")\n"
                 "check:SetCheckedTexture(\"Interface\\\\Buttons\\\\UI-CheckBox-Check\")\n\n"
                 "local function LegacyPanel()\n    if Settings and Settings.RegisterVerticalLayoutCategory then\n"
                 "        return\n    end\n"
                 "    return CreateFrame(\"CheckButton\", nil, panel, \"UICheckButtonTemplate\")\nend\n"
                 "LegacyPanel()\n"},
        "refs": [QUIRKS, UI_SKILL + " — Options page (Settings.CreateCheckbox, legacy fallback)"],
    },
    {
        "id": "UX016", "category": "ux", "title": "Tooltip shown on enter but never hidden on leave",
        "why": "`GameTooltip` is shared by the whole UI. If an OnEnter handler claims it with `SetOwner` and nothing "
               "hides it on OnLeave, the tooltip stays on screen after the mouse moves away, covering the world "
               "until another frame takes it over.",
        "bad": {"core.lua": "local btn = CreateFrame(\"Button\", nil, UIParent, \"UIPanelButtonTemplate\")\n"
                "btn:SetSize(120, 24)\nbtn:SetPoint(\"CENTER\")\nbtn:SetScript(\"OnEnter\", function(self)\n"
                "    GameTooltip:SetOwner(self, \"ANCHOR_RIGHT\")\n    GameTooltip:AddLine(\"Click to refresh\")\n"
                "    GameTooltip:Show()\nend)\n"},
        "good": {"core.lua": "local btn = CreateFrame(\"Button\", nil, UIParent, \"UIPanelButtonTemplate\")\n"
                 "btn:SetSize(120, 24)\nbtn:SetPoint(\"CENTER\")\nbtn:SetScript(\"OnEnter\", function(self)\n"
                 "    GameTooltip:SetOwner(self, \"ANCHOR_RIGHT\")\n    GameTooltip:AddLine(\"Click to refresh\")\n"
                 "    GameTooltip:Show()\nend)\nbtn:SetScript(\"OnLeave\", GameTooltip_Hide)\n"},
        "refs": [NOTES_UI + " (Tooltips)"],
    },
]
