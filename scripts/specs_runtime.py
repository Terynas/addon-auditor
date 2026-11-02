"""Fixture/doc specs for RUNTIME rules. Fixture probes are synthetic AuditorProbe SavedVariables."""

from __future__ import annotations

CORE = "local frame = CreateFrame(\"Frame\")\nframe:RegisterEvent(\"PLAYER_LOGIN\")\n"
PROBE_REF = "`probe/AuditorProbe` (`/probe start`, `/probe stop`, `/reload`), First Timers " \
            "`06-notes/addon-dev/performance-and-resources.md`"


def probe(addon: str, *, mem: list[float] | None = None, cpu: list[float] | None = None, peak: float = 4.0,
          events: int = 1200, duration: float = 600.0, present: bool = True) -> str:
    n = 11
    times = [round(i * duration / (n - 1), 1) for i in range(n)]
    mem = mem or [800.0] * n
    cpu = cpu or [0.2] * n
    name = addon if present else "SomeOtherAddon"

    def arr(xs: list[float]) -> str:
        return "{ " + ", ".join(str(x) for x in xs) + " }"

    return (
        "AuditorProbeDB = {\n"
        "  [\"version\"] = 1,\n"
        "  [\"sessions\"] = {\n"
        "    {\n"
        f"      [\"started\"] = 1793000000, [\"stopped\"] = 1793000600, [\"duration\"] = {duration},\n"
        "      [\"interval\"] = 60, [\"build\"] = \"1.16.0.60000\", [\"interface\"] = 16001,\n"
        "      [\"cpuSource\"] = \"profiler\",\n"
        f"      [\"times\"] = {arr(times)},\n"
        "      [\"addons\"] = {\n"
        f"        [\"{name}\"] = {{ [\"mem\"] = {arr(mem)}, [\"cpu\"] = {arr(cpu)}, [\"peakMs\"] = {peak} }},\n"
        "      },\n"
        f"      [\"events\"] = {{ [\"BAG_UPDATE\"] = {events}, [\"UNIT_AURA@player\"] = 30 }},\n"
        f"      [\"registrations\"] = {{ [\"{name}\"] = {{ \"BAG_UPDATE\", \"UNIT_AURA@player\" }} }},\n"
        "    },\n"
        "  },\n"
        "}\n"
    )


def case(rid: str, title: str, why: str, bad_kw: dict, bad_doc: str, good_doc: str) -> dict:
    return {
        "id": rid, "category": "runtime", "title": title, "why": why,
        "bad": {"core.lua": CORE, "probe.lua": probe("bad", **bad_kw)},
        "good": {"core.lua": CORE, "probe.lua": probe("good")},
        "bad_doc": bad_doc, "good_doc": good_doc, "refs": [PROBE_REF],
    }


SPECS = [
    case("RUN001", "Addon not loaded during the probe session",
         "Runtime rules compare this addon's samples against thresholds. If the probe never saw the addon "
         "(disabled, renamed folder, or the session ran before it loaded) every other RUNTIME rule is "
         "silently skipped, so the audit would look clean without any evidence.",
         {"present": False},
         "-- AuditorProbe.lua: the session lists other addons but not this one",
         "-- AuditorProbe.lua: the session has mem/cpu samples for this addon"),
    case("RUN002", "High memory footprint",
         "Memory is shared by every addon and the UI. Large resident data (full item databases, per-item "
         "tables, cached tooltips) slows garbage collection for everyone and shows up in the in-game "
         "AddOn memory list that players use to decide what to uninstall.",
         {"mem": [9000.0] * 11},
         "-- probe: mem ends at 9000 KB (threshold runtime_memory_kb_warn = 5000)\n"
         "MyAddonDB.cache[itemID] = { name = name, link = link, icon = icon, quality = q }",
         "-- pack rarely used fields, build caches on demand\n"
         "MyAddonDB.cache[itemID] = link"),
    case("RUN003", "Memory keeps growing",
         "A steady upward slope means garbage is produced faster than it is reused, or a cache never "
         "evicts. The Lua GC then runs more often and longer, which shows up as frame-time spikes.",
         {"mem": [1000.0 + 300.0 * i for i in range(11)]},
         "frame:SetScript(\"OnUpdate\", function()\n  local pos = { GetPlayerMapPosition(\"player\") }\nend)",
         "local pos = {}\nframe:SetScript(\"OnUpdate\", function()\n  pos[1], pos[2] = GetPlayerMapPosition(\"player\")\nend)"),
    case("RUN004", "High CPU usage",
         "Addon code runs on the render thread. Every millisecond per second an addon spends is taken "
         "from frame time; above about 1 ms/s it becomes visible in the AddOn profiler and in raids.",
         {"cpu": [3.0] * 11},
         "frame:SetScript(\"OnUpdate\", function(self, elapsed)\n  RefreshEverything()\nend)",
         "frame:SetScript(\"OnUpdate\", function(self, elapsed)\n  self.t = (self.t or 0) + elapsed\n"
         "  if self.t < 0.2 then return end\n  self.t = 0\n  RefreshVisible()\nend)"),
    case("RUN005", "Frame hitch",
         "A single slow frame (one long loop, a full rebuild) is felt as a stutter even if the average "
         "CPU is low. 16.7 ms is the whole budget of a 60 FPS frame.",
         {"peak": 40.0},
         "for i = 1, 20000 do ScanItem(i) end",
         "local co = coroutine.create(function()\n  for i = 1, 20000 do\n    ScanItem(i)\n"
         "    if i % 500 == 0 then coroutine.yield() end\n  end\nend)\n"
         "local function step() if coroutine.resume(co) and coroutine.status(co) ~= \"dead\" then "
         "C_Timer.After(0, step) end end\nstep()"),
    case("RUN006", "Event storm",
         "Each event delivery calls into the addon. Registering broad events (BAG_UPDATE, UNIT_AURA for "
         "every unit, COMBAT_LOG) multiplies work in exactly the situations where the client is busiest.",
         {"events": 200000},
         "frame:RegisterEvent(\"UNIT_AURA\")\nframe:RegisterEvent(\"BAG_UPDATE\")",
         "frame:RegisterUnitEvent(\"UNIT_AURA\", \"player\")\nframe:RegisterEvent(\"BAG_UPDATE_DELAYED\")"),
]
