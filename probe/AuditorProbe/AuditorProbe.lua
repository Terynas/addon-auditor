-- AuditorProbe: runtime sampler for addon-auditor.
-- /probe start [seconds]  begin a session (default sample interval 5s)
-- /probe stop             end the session; /reload or log out to write SavedVariables
-- /probe report           top addons by memory, CPU and event load in chat
-- /probe reset            delete stored sessions
--
-- Data lands in WTF/Account/<ACCOUNT>/SavedVariables/AuditorProbe.lua; feed it to
-- `addon-auditor probe-ingest` or the `ingest_probe` MCP tool.

local ADDON_NAME = ...

local DB_VERSION = 1
local MAX_SESSIONS = 5
local MAX_SAMPLES = 720
local DEFAULT_INTERVAL = 5
local MIN_INTERVAL = 1

local C_AddOns = C_AddOns
local GetNumAddOns = (C_AddOns and C_AddOns.GetNumAddOns) or GetNumAddOns
local GetAddOnInfo = (C_AddOns and C_AddOns.GetAddOnInfo) or GetAddOnInfo
local IsAddOnLoaded = (C_AddOns and C_AddOns.IsAddOnLoaded) or IsAddOnLoaded
local GetTime = GetTime
local floor = math.floor
local tremove = table.remove
local pairs = pairs

local probe = CreateFrame("Frame")
local counters = {}     -- key -> counting frame
local fires = {}        -- key -> count during the active session
local registrations = {} -- addon -> { key = true }
local session, ticker
local lastCpu = {}

local function Print(msg)
    DEFAULT_CHAT_FRAME:AddMessage("|cff66ccffAuditorProbe|r " .. msg)
end

local function CallerAddon()
    local stack = debugstack(3, 4, 0) or ""
    return stack:match("AddOns[/\\]([^/\\]+)[/\\]")
end

local function CountingFrame(key, event, unit1, unit2)
    local f = counters[key]
    if f then
        return f
    end
    f = CreateFrame("Frame")
    local ok
    if unit1 then
        ok = pcall(f.RegisterUnitEvent, f, event, unit1, unit2)
    else
        ok = pcall(f.RegisterEvent, f, event)
    end
    if not ok then
        return nil
    end
    f:SetScript("OnEvent", function()
        if session then
            fires[key] = (fires[key] or 0) + 1
        end
    end)
    counters[key] = f
    return f
end

local function Track(event, unit1, unit2)
    if type(event) ~= "string" then
        return
    end
    local addon = CallerAddon()
    if not addon or addon == ADDON_NAME then
        return
    end
    local key = unit1 and (event .. "@" .. tostring(unit1) .. (unit2 and ("," .. tostring(unit2)) or "")) or event
    if not CountingFrame(key, event, unit1, unit2) then
        return
    end
    local regs = registrations[addon]
    if not regs then
        regs = {}
        registrations[addon] = regs
    end
    regs[key] = true
end

-- Post-hooks only (hooksecurefunc), so secure code keeps its taint state. Each widget type has its own
-- method table; hook every distinct one that can register events.
do
    local hooked = {}
    local function OnRegister(_, event)
        Track(event)
    end
    local function OnRegisterUnit(_, event, unit1, unit2)
        Track(event, unit1, unit2)
    end
    for _, widget in pairs({ "Frame", "Button", "CheckButton", "StatusBar", "Slider", "EditBox", "ScrollFrame" }) do
        local ok, obj = pcall(CreateFrame, widget)
        local mt = ok and obj and getmetatable(obj)
        local methods = mt and mt.__index
        if type(methods) == "table" and not hooked[methods] and methods.RegisterEvent then
            hooked[methods] = true
            hooksecurefunc(methods, "RegisterEvent", OnRegister)
            if methods.RegisterUnitEvent then
                hooksecurefunc(methods, "RegisterUnitEvent", OnRegisterUnit)
            end
        end
    end
end

local function CpuSource()
    if C_AddOnProfiler and C_AddOnProfiler.IsEnabled and C_AddOnProfiler.IsEnabled()
        and Enum and Enum.AddOnProfilerMetric then
        return "profiler"
    end
    if GetCVarBool and GetCVarBool("scriptProfile") and GetAddOnCPUUsage then
        return "scriptProfile"
    end
    return "none"
end

local function LoadedAddons()
    local out = {}
    for i = 1, GetNumAddOns() do
        local name = GetAddOnInfo(i)
        if name and IsAddOnLoaded(i) then
            out[#out + 1] = name
        end
    end
    return out
end

local function Push(list, value)
    list[#list + 1] = value
    if #list > MAX_SAMPLES then
        tremove(list, 1)
    end
end

local function Round(x, places)
    local m = 10 ^ (places or 3)
    return floor(x * m + 0.5) / m
end

local function Sample()
    if not session then
        return
    end
    local now = GetTime()
    local dt = now - (session.lastSample or now)
    session.lastSample = now
    UpdateAddOnMemoryUsage()
    local source = session.cpuSource
    if source == "scriptProfile" then
        UpdateAddOnCPUUsage()
    end
    local fps = GetFramerate and GetFramerate() or 60
    local metrics = Enum and Enum.AddOnProfilerMetric
    for _, name in pairs(session.watch) do
        local a = session.addons[name]
        Push(a.mem, Round(GetAddOnMemoryUsage(name), 1))
        if source == "profiler" then
            local perFrame = C_AddOnProfiler.GetAddOnMetric(name, metrics.RecentAverageTime) or 0
            Push(a.cpu, Round(perFrame * fps))
            local peak = C_AddOnProfiler.GetAddOnMetric(name, metrics.PeakTime) or 0
            if peak > (a.peakMs or 0) then
                a.peakMs = Round(peak)
            end
        elseif source == "scriptProfile" then
            local total = GetAddOnCPUUsage(name) or 0
            local prev = lastCpu[name]
            lastCpu[name] = total
            if prev and dt > 0 then
                Push(a.cpu, Round((total - prev) / dt))
            end
        end
    end
    Push(session.times, Round(now - session.startedAt, 1))
end

local function Start(interval)
    if session then
        Print("already running; /probe stop first")
        return
    end
    interval = math.max(MIN_INTERVAL, tonumber(interval) or DEFAULT_INTERVAL)
    wipe(fires)
    wipe(lastCpu)
    local version, build, _, iface = GetBuildInfo()
    session = {
        started = time(),
        startedAt = GetTime(),
        interval = interval,
        build = version .. "." .. tostring(build),
        interface = iface,
        cpuSource = CpuSource(),
        watch = LoadedAddons(),
        addons = {},
        times = {},
    }
    for _, name in pairs(session.watch) do
        session.addons[name] = { mem = {}, cpu = {} }
    end
    Sample()
    ticker = C_Timer.NewTicker(interval, Sample)
    Print(("started: %d addons, every %ds, CPU source: %s"):format(#session.watch, interval, session.cpuSource))
    if session.cpuSource == "none" then
        Print("no CPU data: enable the AddOn profiler (Mainline) or /console scriptProfile 1 and /reload")
    end
end

local function Stop()
    if not session then
        Print("not running")
        return
    end
    ticker:Cancel()
    ticker = nil
    Sample()
    session.duration = Round(GetTime() - session.startedAt, 1)
    session.stopped = time()
    session.events = {}
    for key, n in pairs(fires) do
        session.events[key] = n
    end
    session.registrations = {}
    for addon, keys in pairs(registrations) do
        local list = {}
        for key in pairs(keys) do
            list[#list + 1] = key
        end
        table.sort(list)
        session.registrations[addon] = list
    end
    session.watch, session.startedAt, session.lastSample = nil, nil, nil
    local sessions = AuditorProbeDB.sessions
    sessions[#sessions + 1] = session
    while #sessions > MAX_SESSIONS do
        tremove(sessions, 1)
    end
    Print(("stopped after %ds; /reload to write SavedVariables"):format(session.duration))
    session = nil
end

local function Report()
    local s = session or AuditorProbeDB.sessions[#AuditorProbeDB.sessions]
    if not s then
        Print("no data; /probe start")
        return
    end
    local rows = {}
    for name, a in pairs(s.addons) do
        local mem = a.mem[#a.mem] or 0
        local cpu = 0
        for i = 1, #a.cpu do
            cpu = cpu + a.cpu[i]
        end
        rows[#rows + 1] = { name = name, mem = mem, cpu = #a.cpu > 0 and cpu / #a.cpu or 0 }
    end
    table.sort(rows, function(x, y) return x.mem > y.mem end)
    Print("top memory (KB) / avg CPU (ms/s):")
    for i = 1, math.min(10, #rows) do
        local r = rows[i]
        Print(("  %s: %.0f KB, %.2f ms/s"):format(r.name, r.mem, r.cpu))
    end
end

local function Help()
    Print("/probe start [seconds] | stop | report | reset")
end

SLASH_AUDITORPROBE1 = "/probe"
SlashCmdList.AUDITORPROBE = function(msg)
    local cmd, arg = (msg or ""):lower():match("^%s*(%S*)%s*(.-)%s*$")
    if cmd == "start" then
        Start(arg)
    elseif cmd == "stop" then
        Stop()
    elseif cmd == "report" then
        Report()
    elseif cmd == "reset" then
        if session then
            Print("stop the running session first")
        else
            wipe(AuditorProbeDB.sessions)
            Print("sessions cleared")
        end
    else
        Help()
    end
end

probe:SetScript("OnEvent", function(self, event, name)
    if event == "ADDON_LOADED" and name == ADDON_NAME then
        if type(AuditorProbeDB) ~= "table" or AuditorProbeDB.version ~= DB_VERSION then
            AuditorProbeDB = { version = DB_VERSION, sessions = {} }
        end
        self:UnregisterEvent("ADDON_LOADED")
    elseif event == "PLAYER_LOGOUT" and session then
        Stop()
    end
end)
probe:RegisterEvent("ADDON_LOADED")
probe:RegisterEvent("PLAYER_LOGOUT")
