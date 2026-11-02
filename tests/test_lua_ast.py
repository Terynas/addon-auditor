from __future__ import annotations

import pytest

from addon_auditor.core.lua_ast import LuaSyntaxError, call_name, dotted_name, parse


def test_parses_wow_style_code() -> None:
    src = """
local addonName, ns = ...
local f = CreateFrame("Frame", "MyFrame", UIParent, "BackdropTemplate")
f:SetScript("OnEvent", function(self, event, ...) return self[event](self, ...) end)
function ns.Module:Init(a, b) local t = {1, 2, x = 3, [4] = "y"}; return #t .. "s" end
local s = [==[long ]] string]==] --[[ block
comment ]] local n = 0x1F + 1e3 - .5
"""
    chunk, comments = parse(src)
    assert any(c.text.strip().startswith("block") for c in comments)
    names = [call_name(n) for n in chunk.walk() if n.kind in ("Call", "Method")]
    assert "CreateFrame" in names and ":SetScript" in names


def test_scope_resolution_marks_globals() -> None:
    chunk, _ = parse("local a = 1\nb = a\nlocal function g() return c end\n")
    names = {(n.id, n.a.get("is_global")) for n in chunk.walk() if n.kind == "Name" and not n.a.get("is_decl")}
    assert ("a", False) in names
    assert ("b", True) in names
    assert ("c", True) in names


def test_dotted_name() -> None:
    chunk, _ = parse("C_Timer.After(1, f)")
    call = next(n for n in chunk.walk() if n.kind == "Call")
    assert dotted_name(call.func) == "C_Timer.After"


def test_syntax_error_has_position() -> None:
    with pytest.raises(LuaSyntaxError) as e:
        parse("local x = \nif then end")
    assert e.value.line == 2


def test_walk_terminates_with_scope_links() -> None:
    chunk, _ = parse("local x = 1\nlocal function f() return x + x end\nf()\n")
    assert sum(1 for _ in chunk.walk()) < 100
