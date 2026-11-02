local MAJOR, MINOR = "LibFoo-1.0", 3
local lib = LibStub:NewLibrary(MAJOR, MINOR)
if not lib then return end
