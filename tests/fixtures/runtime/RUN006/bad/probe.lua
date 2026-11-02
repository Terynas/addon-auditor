AuditorProbeDB = {
  ["version"] = 1,
  ["sessions"] = {
    {
      ["started"] = 1793000000, ["stopped"] = 1793000600, ["duration"] = 600.0,
      ["interval"] = 60, ["build"] = "1.16.0.60000", ["interface"] = 16001,
      ["cpuSource"] = "profiler",
      ["times"] = { 0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 360.0, 420.0, 480.0, 540.0, 600.0 },
      ["addons"] = {
        ["bad"] = { ["mem"] = { 800.0, 800.0, 800.0, 800.0, 800.0, 800.0, 800.0, 800.0, 800.0, 800.0, 800.0 }, ["cpu"] = { 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2 }, ["peakMs"] = 4.0 },
      },
      ["events"] = { ["BAG_UPDATE"] = 200000, ["UNIT_AURA@player"] = 30 },
      ["registrations"] = { ["bad"] = { "BAG_UPDATE", "UNIT_AURA@player" } },
    },
  },
}
