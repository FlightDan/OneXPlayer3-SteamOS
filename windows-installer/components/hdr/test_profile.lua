-- Run with Lua/LuaJIT against a generated Gamescope profile, outside Gamescope.
local profile_path = assert(arg[1], "Usage: lua test_profile.lua PROFILE.lua")
local hooks, logs
local function load_profile()
    hooks, logs = {}, {}
    gamescope = {
        config = {known_displays = {}},
        convars = {composite_force = {value = false}, hdr_enabled = {value = false}},
        eotf = {gamma22 = 22},
        log_priority = {info = "info", warning = "warning"},
        hook = function(name, fn)
            assert(hooks[name] == nil, "duplicate hook: " .. name)
            hooks[name] = fn
        end,
        log = function(priority, message) logs[#logs + 1] = message end,
        modegen = {
            adjust_front_porch = function(mode, porch) mode.porch = porch end,
            calc_vrefresh = function(mode) return 380160000 / (2000 * (1200 + 64 + mode.porch)) end,
        },
    }
    debug = function() end
    warn = function() end
    dofile(profile_path)
    return assert(gamescope.config.known_displays.oxp3_sdc_oled)
end

local display = load_profile()
assert(display.hdr.eotf == 22, "Gamma 2.2 output required")
assert(display.hdr.supported and display.hdr.force_enabled)
assert(display.hdr.max_content_light_level == 1100, "peak mapping regressed")
assert(display.hdr.max_frame_average_luminance == 472, "full-frame mapping regressed")
assert(display.hdr.min_content_light_level == 0.0005)
assert(display.colorimetry.r.x == 0.6835 and display.colorimetry.w.y == 0.3291)
for _, invalid in ipairs({
    {vendor = "OTHER", model = "AMS881KB01-0"},
    {vendor = "SDC", model = "AMS881KB01-1"},
    {vendor = "SDC", model = "prefix-AMS881KB01-0"},
    {vendor = "SDC"},
}) do
    assert(display.matches(invalid) == -1, "unrelated panel matched")
    assert(not gamescope.convars.composite_force.value, "unrelated panel forced composition")
end
assert(type(hooks.OnPostPaint) == "function", "composition recovery missing")
hooks.OnPostPaint()
assert(not gamescope.convars.composite_force.value, "hook acted before panel match")
assert(display.matches({vendor = "SDC", model = "AMS881KB01-0 "}) == 6000)
assert(gamescope.convars.composite_force.value, "first-frame composition missing")
for _, hdr in ipairs({false, true}) do
    gamescope.convars.hdr_enabled.value = hdr
    gamescope.convars.composite_force.value = false -- Simulate Steam property override.
    hooks.OnPostPaint()
    assert(gamescope.convars.composite_force.value, "Steam override was not corrected")
    local before = #logs
    hooks.OnPostPaint()
    assert(#logs == before, "stable frames should not flood logs")
end
for index, rate in ipairs(display.dynamic_refresh_rates) do
    assert(rate == index + 29, "refresh rates changed")
end
assert(#display.dynamic_refresh_rates == 115)
for rate, porch in pairs({[60] = 1904, [144] = 56}) do
    local mode = display.dynamic_modegen({}, rate)
    assert(mode.porch == porch, "native mode anchor changed")
    assert(math.abs(mode.vrefresh - rate) < 0.01)
end
local fallback = {}
assert(display.dynamic_modegen(fallback, 29) == fallback)
print("PASS: gamma22 1100/472; exact panel; initial composition; SDR/HDR override recovery; VRR anchors")
