-- This Script is Part of the Prometheus Obfuscator by Levno_710
--
-- test.lua
-- This script contains the Code for the Prometheus CLI

-- Configure package.path for requiring Prometheus
local function script_path()
	local str = debug.getinfo(2, "S").source:sub(2)
	return str:match("(.*[/%\\])") or "";
end
local base = script_path(); package.path = base .. "?.lua;" .. base .. "src/?.lua;" .. base .. "src/?/?.lua;" .. package.path;
require("src.cli");